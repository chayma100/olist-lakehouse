import pytest

from agent.config import Config
from agent.graph_react_baseline import run_agent
from agent.tools import DuckDBBackend, ToolContext, create_chart, run_sql


@pytest.fixture
def ctx(tmp_path):
    cfg = Config(allowed_tables=["fact_orders", "dim_customers"], output_dir=str(tmp_path),
                 max_steps=4, preview_rows=3, sql_backend="duckdb", table_prefix="")
    backend = DuckDBBackend()
    backend.con.execute("CREATE TABLE fact_orders AS SELECT i AS order_id, i % 3 AS customer_id, "
                        "i * 10.0 AS revenue FROM range(1, 11) t(i)")
    backend.con.execute("CREATE TABLE dim_customers AS SELECT * FROM (VALUES (0,'SP'),(1,'RJ'),(2,'MG')) "
                        "t(customer_id, state)")
    return ToolContext(cfg=cfg, backend=backend)


class FakeLLM:
    """Rejoue des réponses scriptées : permet de tester la boucle sans API."""
    def __init__(self, script):
        self.script = list(script)

    def chat(self, messages, tools):
        return self.script.pop(0)


def call(name, **args):
    return {"content": "", "usage": (10, 5),
            "tool_calls": [{"id": f"id_{name}", "name": name, "arguments": args}]}


def final(text):
    return {"content": text, "tool_calls": [], "usage": (10, 5)}


def test_run_sql_preview_and_result_id(ctx):
    r = run_sql(ctx, sql="SELECT * FROM fact_orders")
    assert r.success and r.metadata["rows"] == 10
    assert r.metadata["result_id"] in ctx.results
    assert "first 3 of 10 rows" in r.result_for_llm


def test_run_sql_blocks_bad_query(ctx):
    r = run_sql(ctx, sql="DROP TABLE fact_orders")
    assert not r.success and r.metadata["blocked"]


def test_run_sql_returns_sql_error_to_llm(ctx):
    r = run_sql(ctx, sql="SELECT nope FROM fact_orders")
    assert not r.success and "SQL error" in r.result_for_llm


def test_chart(ctx):
    rid = run_sql(ctx, sql="SELECT order_id, revenue FROM fact_orders").metadata["result_id"]
    r = create_chart(ctx, result_id=rid, chart_type="bar", x="order_id", y="revenue", title="t")
    assert r.success
    import os
    assert os.path.exists(r.metadata["chart_path"])
    assert not create_chart(ctx, result_id=rid, chart_type="bar", x="zzz", y="revenue").success
    assert not create_chart(ctx, result_id="r_nope", chart_type="bar", x="a", y="b").success


def test_loop_sql_then_answer(ctx):
    llm = FakeLLM([call("run_sql", sql="SELECT COUNT(*) AS n FROM fact_orders"), final("There are 10 orders.")])
    run = run_agent("How many orders?", llm, ctx)
    assert run.answer == "There are 10 orders."
    assert run.stopped_reason == "answered" and run.steps == 2
    assert run.trace[0]["tool"] == "run_sql" and run.trace[0]["success"]


def test_loop_recovers_from_sql_error(ctx):
    llm = FakeLLM([call("run_sql", sql="SELECT bad FROM fact_orders"),
                   call("run_sql", sql="SELECT COUNT(*) FROM fact_orders"), final("10")])
    run = run_agent("count", llm, ctx)
    assert [t["success"] for t in run.trace] == [False, True]


def test_loop_max_steps(ctx):
    llm = FakeLLM([call("run_sql", sql="SELECT 1 FROM fact_orders")] * 4)
    run = run_agent("loop forever", llm, ctx)
    assert run.stopped_reason == "max_steps"


def test_loop_unknown_tool_and_bad_args(ctx):
    llm = FakeLLM([call("hack"), call("run_sql", wrong_arg=1), final("done")])
    run = run_agent("x", llm, ctx)
    assert run.trace[0]["success"] is False
    assert run.answer == "done"


def test_empty_question_blocked(ctx):
    run = run_agent("   ", FakeLLM([]), ctx)
    assert run.stopped_reason == "blocked"


def test_ask_user_without_user(ctx):
    llm = FakeLLM([call("ask_user", question="Which year?"), final("Assuming all years.")])
    run = run_agent("revenue?", llm, ctx)
    assert run.trace[0]["success"] is False
