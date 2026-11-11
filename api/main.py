"""api/main.py : endpoints pour tester l'agent, ses tools, ses garde-fous et sa latence.

Lancer (depuis la racine du projet) :
    uvicorn api.main:app --reload
Documentation interactive (tester sans code) :
    http://127.0.0.1:8000/docs
"""
import json
import os
import re
import time
from collections import OrderedDict
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.config import Config
from agent.graph_react_baseline import run_agent
from agent.guardrails import input_guard, validate_sql
from agent.runlog import read_runs, stats
from agent.state import NeedsUserInput
from agent.tools import TOOLS, ToolContext, make_backend
from agent.tracing import enabled as tracing_enabled


class AskRequest(BaseModel):
    question: str
    clarification: str | None = Field(
        None, description="Réponse de l'utilisateur après un statut 'needs_input'.")


class SqlRequest(BaseModel):
    sql: str


class InputRequest(BaseModel):
    question: str


def _no_terminal(question: str) -> str:
    """ask_user dans l'API : on s'arrête et on renvoie la question au client."""
    raise NeedsUserInput(question)


def create_app(cfg: Config | None = None, llm=None, backend=None) -> FastAPI:
    """Fabrique l'application. Les paramètres servent aux tests (faux LLM, base locale)."""
    app = FastAPI(title="Olist text-to-SQL agent", version="0.1")
    app.add_middleware(CORSMiddleware, allow_origins=(cfg or Config()).cors_origins,
                       allow_methods=["*"], allow_headers=["*"])

    @lru_cache(maxsize=1)
    def parts():
        c = cfg or Config()
        return c, (llm if llm is not None else _make_llm(c)), (backend or make_backend(c))

    sandbox: dict = {}   # contexte partagé des endpoints /tools : result_id réutilisables
    results_cache: OrderedDict = OrderedDict()   # derniers résultats SQL (pour le dashboard)

    def remember(results: dict) -> None:
        for rid, df in results.items():
            results_cache[rid] = df
            results_cache.move_to_end(rid)
        while len(results_cache) > 50:
            results_cache.popitem(last=False)

    def sandbox_ctx() -> ToolContext:
        c, _, b = parts()
        if "ctx" not in sandbox:
            sandbox["ctx"] = ToolContext(cfg=c, backend=b, ask_fn=_no_terminal)
        return sandbox["ctx"]

    # ------------------------------------------------------------ santé

    @app.get("/health")
    def health():
        c = cfg or Config()
        return {"status": "ok", "sql_backend": c.sql_backend, "model": c.llm_model,
                "tracing": {"langsmith": tracing_enabled(),
                            "project": os.getenv("LANGSMITH_PROJECT", "default")},
                "tables": c.allowed_tables, "limits": {
                    "max_steps": c.max_steps, "max_rows": c.max_rows,
                    "max_tool_calls": c.max_tool_calls, "max_tokens_per_run": c.max_tokens_per_run}}

    # ------------------------------------------------------------ agent complet

    @app.post("/ask")
    def ask(req: AskRequest):
        c, model, b = parts()
        question = req.question if not req.clarification else (
            f"{req.question}\n\n[User clarification: {req.clarification}]")
        ctx = ToolContext(cfg=c, backend=b, ask_fn=_no_terminal)
        run = run_agent(question, model, ctx)
        remember(ctx.results)
        charts = [f"/charts/{os.path.basename(t['chart_path'])}" for t in run.trace if t.get("chart_path")]
        return {
            "run_id": run.run_id, "status": run.stopped_reason, "answer": run.answer,
            "charts": charts, "warnings": run.warnings, "steps": run.steps,
            "latency_s": run.latency_s, "llm_time_s": run.llm_time_s, "tools_time_s": run.tools_time_s,
            "tokens": {"prompt": run.prompt_tokens, "completion": run.completion_tokens},
            "backend": run.backend, "model": run.model, "trace": run.trace,
        }

    # ------------------------------------------------------------ tools un par un

    @app.post("/tools/{name}")
    def call_tool(name: str, args: dict):
        """Appelle un tool directement (mêmes garde-fous). Les result_id restent valables
        entre appels : lancer run_sql, puis create_chart avec le result_id obtenu."""
        if name not in TOOLS:
            raise HTTPException(404, f"Unknown tool '{name}'. Available: {sorted(TOOLS)}")
        t0 = time.perf_counter()
        try:
            r = TOOLS[name](sandbox_ctx(), **args)
        except NeedsUserInput as e:
            return {"tool": name, "needs_input": e.question, "latency_s": round(time.perf_counter() - t0, 3)}
        except TypeError as e:
            raise HTTPException(422, f"Invalid arguments: {e}") from e
        remember(sandbox_ctx().results)
        return {"tool": name, "success": r.success, "result_for_llm": r.result_for_llm,
                "error": r.error, "metadata": r.metadata, "latency_s": round(time.perf_counter() - t0, 3)}

    @app.get("/results/{result_id}")
    def result(result_id: str, limit: int = 100):
        """Contenu d'un résultat SQL (pour afficher le tableau dans le dashboard)."""
        df = results_cache.get(result_id)
        if df is None:
            raise HTTPException(404, f"Unknown result_id '{result_id}'")
        part = df.head(min(limit, 500))
        data = json.loads(part.to_json(orient="split", date_format="iso"))
        return {"columns": data["columns"], "rows": data["data"], "row_count": len(df)}

    @app.get("/charts/{filename}")
    def chart(filename: str):
        if not re.fullmatch(r"chart_[0-9a-f]+\.png", filename):
            raise HTTPException(404, "Not found")
        path = os.path.join((cfg or Config()).output_dir, filename)
        if not os.path.exists(path):
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="image/png")

    # ------------------------------------------------------------ garde-fous seuls

    @app.post("/guard/input")
    def guard_input(req: InputRequest):
        r = input_guard(req.question)
        return {"allowed": r.ok, "reason": r.reason}

    @app.post("/guard/sql")
    def guard_sql(req: SqlRequest):
        c = cfg or Config()
        r = validate_sql(req.sql, c.allowed_tables, c.max_rows)
        return {"allowed": r.ok, "reason": r.reason, "final_sql": r.sql}

    # ------------------------------------------------------------ observabilité

    @app.get("/runs")
    def runs(limit: int = 20):
        return read_runs((cfg or Config()).runs_dir, min(limit, 200))

    @app.get("/stats")
    def get_stats():
        return stats((cfg or Config()).runs_dir)

    return app


def _make_llm(cfg: Config):
    from agent.llm import LLM
    return LLM(cfg)


app = create_app()
