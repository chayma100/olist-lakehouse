"""graph_react_baseline.py : la boucle de l'agent (harness).

Le LLM décide, le code exécute les tools et renvoie les résultats, jusqu'à une réponse
finale ou jusqu'à une limite (étapes, appels de tools, tokens). Les garde-fous sont
appliqués par le code : entrée avant le LLM, SQL dans run_sql, sortie après la réponse.
"""
import json
import time

from .config import Config
from .guardrails import input_guard, ungrounded_numbers
from .prompts import build_system_prompt
from .runlog import write_run
from .state import AgentRun, NeedsUserInput
from .tools import TOOL_SPECS, TOOLS, ToolContext
from .tracing import trace, traced_call


def _loop(run: AgentRun, llm, ctx: ToolContext, system_prompt: str | None, sources: list[str]) -> None:
    cfg: Config = ctx.cfg
    messages = [
        {"role": "system", "content": system_prompt or build_system_prompt()},
        {"role": "user", "content": run.question},
    ]
    for step in range(1, cfg.max_steps + 1):
        run.steps = step
        t_llm = time.perf_counter()
        try:
            resp = llm.chat(messages, TOOL_SPECS)
        except Exception as e:
            run.answer, run.stopped_reason = f"LLM error: {e}", "error"
            return
        run.llm_time_s += time.perf_counter() - t_llm
        run.prompt_tokens += resp["usage"][0]
        run.completion_tokens += resp["usage"][1]

        if not resp["tool_calls"]:
            run.answer = resp["content"]
            return
        if run.prompt_tokens + run.completion_tokens > cfg.max_tokens_per_run:
            run.answer, run.stopped_reason = "Stopped: token budget exceeded.", "budget"
            return

        messages.append({
            "role": "assistant",
            "content": resp["content"] or None,
            "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                for c in resp["tool_calls"]
            ],
        })
        for call in resp["tool_calls"]:
            run.tool_calls += 1
            if run.tool_calls > cfg.max_tool_calls:
                run.answer, run.stopped_reason = "Stopped: too many tool calls.", "budget"
                return
            ts = time.perf_counter()
            fn = TOOLS.get(call["name"])
            if fn is None:
                result_text, ok, meta = f"Unknown tool '{call['name']}'.", False, {}
            else:
                try:
                    r = traced_call(call["name"], "tool", fn, ctx, **call["arguments"])
                    result_text, ok, meta = r.result_for_llm, r.success, dict(r.metadata)
                    if r.error:
                        meta["error"] = r.error
                    if ok:
                        sources.append(result_text)
                except NeedsUserInput as e:   # interface sans terminal : on rend la main
                    run.answer, run.stopped_reason = e.question, "needs_input"
                    run.trace.append({"step": step, "tool": call["name"], "arguments": call["arguments"],
                                      "success": True, "latency_s": 0.0, "needs_input": True})
                    return
                except TypeError as e:  # arguments incorrects envoyés par le LLM
                    result_text, ok, meta = f"Invalid arguments: {e}", False, {}
            elapsed = time.perf_counter() - ts
            run.tools_time_s += elapsed
            run.trace.append({
                "step": step, "tool": call["name"], "arguments": call["arguments"],
                "success": ok, "latency_s": round(elapsed, 3), **meta,
            })
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result_text})
    run.stopped_reason = "max_steps"
    run.answer = "I could not finish within the allowed number of steps."


@trace("olist_agent", "chain")
def run_agent(question: str, llm, ctx: ToolContext, system_prompt: str | None = None) -> AgentRun:
    cfg: Config = ctx.cfg
    run = AgentRun(question=question, backend=cfg.sql_backend, model=cfg.llm_model)
    t0 = time.perf_counter()
    sources: list[str] = []

    guard = input_guard(question)
    if not guard.ok:
        run.answer, run.stopped_reason = guard.reason, "blocked"
    else:
        _loop(run, llm, ctx, system_prompt, sources)
        if run.stopped_reason == "answered":
            bad = ungrounded_numbers(run.answer, sources + [question])
            if bad:
                run.warnings.append(f"Numbers not found in tool results (check them): {', '.join(bad)}")

    run.latency_s = round(time.perf_counter() - t0, 3)
    run.llm_time_s, run.tools_time_s = round(run.llm_time_s, 3), round(run.tools_time_s, 3)
    try:
        write_run(run, cfg.runs_dir)
    except OSError:
        pass   # le journal ne doit jamais casser l'agent
    return run
