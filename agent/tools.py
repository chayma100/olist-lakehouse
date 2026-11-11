"""tools.py : les 4 tools (specs vues par le LLM + implémentations).

Pattern result_id : le résultat complet reste côté code (ResultStore), le LLM
ne reçoit qu'un aperçu et un identifiant à réutiliser (ex. pour un graphique).
"""
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from .config import Config
from .guardrails import validate_sql
from .state import ToolResult

# ---------------------------------------------------------------- backends SQL


class DuckDBBackend:
    """Pour les tests locaux et le secours parquet."""

    def __init__(self, path: str = ":memory:"):
        import duckdb
        self.con = duckdb.connect(path)

    def run(self, sql: str) -> pd.DataFrame:
        return self.con.execute(sql).df()


class DatabricksBackend:
    """SQL warehouse Databricks via databricks-sql-connector.
    La connexion est ouverte une fois puis réutilisée (se connecter coûte plusieurs
    secondes). Un backend MCP pourra être ajouté avec la même méthode run()."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._conn = None
        self._lock = threading.Lock()   # une connexion = une requête à la fois

    def _connect(self):
        from databricks import sql as dbsql
        return dbsql.connect(
            server_hostname=self.cfg.databricks_hostname,
            http_path=self.cfg.databricks_http_path,
            access_token=self.cfg.databricks_token,
        )

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _execute(self, sql: str):
        with self._conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall(), [d[0] for d in cur.description]

    def run(self, sql: str) -> pd.DataFrame:
        with self._lock:
            return self._run_locked(sql)

    def _run_locked(self, sql: str) -> pd.DataFrame:
        reused = self._conn is not None
        if self._conn is None:
            self._conn = self._connect()
        try:
            rows, columns = self._execute(sql)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            if not reused:
                raise
            # la connexion réutilisée a peut-être expiré : une seule nouvelle tentative
            self._conn = self._connect()
            rows, columns = self._execute(sql)
        df = pd.DataFrame([tuple(r) for r in rows], columns=columns)
        # DECIMAL arrive en objets Decimal : on convertit en nombres (calculs, graphiques)
        import decimal
        for col in df.columns:
            first = df[col].dropna()
            if len(first) and isinstance(first.iloc[0], decimal.Decimal):
                df[col] = df[col].astype(float)
        return df


def make_backend(cfg: Config):
    if cfg.sql_backend == "mcp":
        from .mcp_backend import McpBackend
        return McpBackend(cfg)
    if cfg.sql_backend == "databricks":
        return DatabricksBackend(cfg)
    return DuckDBBackend(cfg.duckdb_path)


# ---------------------------------------------------------------- contexte


@dataclass
class ToolContext:
    cfg: Config
    backend: object
    results: dict[str, pd.DataFrame] = field(default_factory=dict)
    ask_fn: Callable[[str], str] | None = None   # fournie par l'interface (CLI, API)


# ---------------------------------------------------------------- implémentations


def run_sql(ctx: ToolContext, sql: str = "", **_) -> ToolResult:
    guard = validate_sql(sql, ctx.cfg.allowed_tables, ctx.cfg.max_rows)
    if not guard.ok:
        return ToolResult(False, f"Query rejected: {guard.reason}", error=guard.reason,
                          metadata={"blocked": True})
    final_sql = guard.sql
    if ctx.cfg.sql_backend in ("databricks", "mcp") and ctx.cfg.table_prefix:
        final_sql = _prefix_tables(final_sql, ctx.cfg)
    try:
        df = ctx.backend.run(final_sql)
    except Exception as e:  # erreur SQL renvoyée au LLM pour qu'il corrige
        return ToolResult(False, f"SQL error: {e}", error=str(e), metadata={"sql": final_sql})

    rid = "r_" + uuid.uuid4().hex[:6]
    ctx.results[rid] = df
    if df.empty:
        text = f"Query returned 0 rows. result_id={rid}"
    else:
        preview = df.head(ctx.cfg.preview_rows).to_csv(index=False)
        more = (f"\n(preview: first {ctx.cfg.preview_rows} of {len(df)} rows. "
                f"Do not re-run the query just to see the rest: aggregate, filter or add ORDER BY/LIMIT instead.)"
                if len(df) > ctx.cfg.preview_rows else "")
        text = f"{preview}{more}\nresult_id={rid} rows={len(df)}"
    return ToolResult(True, text, metadata={"sql": final_sql, "result_id": rid, "rows": len(df)})


def _prefix_tables(sql: str, cfg: Config) -> str:
    import sqlglot
    from sqlglot import exp
    tree = sqlglot.parse_one(sql, read="databricks")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if t.name.lower() in ctes or t.args.get("db"):
            continue
        catalog, _, schema = cfg.table_prefix.rpartition(".")
        t.set("db", exp.to_identifier(schema))
        if catalog:
            t.set("catalog", exp.to_identifier(catalog))
    return tree.sql(dialect="databricks")


CHART_TYPES = ["line", "bar", "hist", "scatter"]


def create_chart(ctx: ToolContext, result_id: str = "", chart_type: str = "", x: str = "",
                 y: str | None = None, title: str = "", **_) -> ToolResult:
    df = ctx.results.get(result_id)
    if df is None:
        return ToolResult(False, f"Unknown result_id '{result_id}'. Run run_sql first.",
                          error="unknown_result_id")
    if chart_type not in CHART_TYPES:
        return ToolResult(False, f"chart_type must be one of {CHART_TYPES}.", error="bad_chart_type")
    for col in [c for c in (x, y) if c]:
        if col not in df.columns:
            return ToolResult(False, f"Column '{col}' not found. Columns: {list(df.columns)}",
                              error="bad_column")
    if chart_type != "hist" and not y:
        return ToolResult(False, f"chart_type '{chart_type}' needs a y column.", error="missing_y")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5))
    if chart_type == "line":
        ax.plot(df[x], df[y])
    elif chart_type == "bar":
        ax.bar(df[x].astype(str), df[y])
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    elif chart_type == "hist":
        ax.hist(df[x].dropna(), bins=20)
    else:
        ax.scatter(df[x], df[y])
    ax.set_title(title or "")
    ax.set_xlabel(x)
    if y:
        ax.set_ylabel(y)
    fig.tight_layout()
    os.makedirs(ctx.cfg.output_dir, exist_ok=True)
    path = os.path.join(ctx.cfg.output_dir, f"chart_{uuid.uuid4().hex[:6]}.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return ToolResult(True, f"Chart created: {path}", metadata={"chart_path": path})


def search_reviews(ctx: ToolContext, query: str = "", **_) -> ToolResult:
    # TODO jalon RAG : BM25 + embeddings sur gold.fact_reviews
    return ToolResult(False, "search_reviews is not available yet.", error="not_implemented")


def ask_user(ctx: ToolContext, question: str = "", **_) -> ToolResult:
    if ctx.ask_fn is None:
        return ToolResult(False, "No user is available to answer. Make a reasonable assumption "
                                 "and state it in your answer.", error="no_user")
    return ToolResult(True, f"User answered: {ctx.ask_fn(question)}")


# ---------------------------------------------------------------- table nom -> fonction

TOOLS: dict[str, Callable[..., ToolResult]] = {
    "run_sql": run_sql,
    "create_chart": create_chart,
    "search_reviews": search_reviews,
    "ask_user": ask_user,
}

# ---------------------------------------------------------------- specs (format OpenAI)


def _spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


TOOL_SPECS = [
    _spec("run_sql",
          "Execute ONE read-only SELECT query on the gold tables. Returns a preview of the "
          "rows and a result_id. Use exact table and column names from the schema.",
          {"sql": {"type": "string", "description": "A single SELECT statement."}}, ["sql"]),
    _spec("create_chart",
          "Draw a chart from a previous run_sql result. Use only when the user asks for a "
          "chart or graph.",
          {"result_id": {"type": "string", "description": "result_id returned by run_sql."},
           "chart_type": {"type": "string", "enum": CHART_TYPES},
           "x": {"type": "string", "description": "Column for the x axis."},
           "y": {"type": "string", "description": "Column for the y axis (not needed for hist)."},
           "title": {"type": "string"}},
          ["result_id", "chart_type", "x"]),
    _spec("search_reviews",
          "Search customer review comments (Portuguese). Write the query in Portuguese. "
          "Use for questions about WHY customers are happy or unhappy.",
          {"query": {"type": "string", "description": "Search query in Portuguese."}}, ["query"]),
    _spec("ask_user",
          "Ask the user a short clarification question. Use only if the request is truly "
          "ambiguous and a reasonable assumption is not possible.",
          {"question": {"type": "string"}}, ["question"]),
]
