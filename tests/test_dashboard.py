import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import dashboard.client as client_mod  # noqa: E402

REPLY = {
    "run_id": "abc123", "status": "answered", "answer": "There are 5 orders.", "charts": [],
    "warnings": ["Numbers not found in tool results (check them): 98765.43"], "steps": 2,
    "latency_s": 1.5, "llm_time_s": 0.9, "tools_time_s": 0.6, "tokens": {"prompt": 100, "completion": 20},
    "backend": "duckdb", "model": "fake", "trace": [
        {"step": 1, "tool": "run_sql", "success": True, "latency_s": 0.6,
         "sql": "SELECT COUNT(*) FROM fact_orders LIMIT 100", "result_id": "r_1", "rows": 1}],
}


@pytest.fixture
def fake_api(monkeypatch):
    calls = {"ask": []}

    def request(self, method, path, **kwargs):
        class R:
            status_code = 200
            content = b""

            def json(_):
                return data(path, kwargs)
        return R()

    def data(path, kwargs):
        if path == "/health":
            return {"status": "ok", "sql_backend": "duckdb", "model": "fake",
                    "tracing": {"langsmith": True, "project": "olist-agent"}}
        if path == "/ask":
            calls["ask"].append(kwargs["json"])
            q = kwargs["json"]["question"]
            if "Which year" in q or kwargs["json"].get("clarification"):
                return {**REPLY, "answer": "Revenue for 2017: 1000.00"}
            if q == "ambiguous":
                return {**REPLY, "status": "needs_input", "answer": "Which year?", "trace": []}
            return REPLY
        if path.startswith("/results/"):
            return {"columns": ["n"], "rows": [[5]], "row_count": 1}
        if path == "/runs":
            return [{"run_id": "abc123", "timestamp": "2026-11-11T10:00:00", "question": "q",
                     "stopped_reason": "answered", "steps": 2, "latency_s": 1.5, "llm_time_s": 0.9,
                     "tools_time_s": 0.6, "backend": "duckdb", "model": "fake"}]
        if path == "/stats":
            return {"runs": 1, "answered_rate": 1.0, "latency_s": {"mean": 1.5, "p50": 1.5, "p95": 1.5},
                    "avg_tokens": 120}
        return {}

    monkeypatch.setattr(client_mod.ApiClient, "_request", request)
    return calls


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_app():
    at = AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=30)
    at.run()
    return at


def test_app_loads_and_shows_health(fake_api):
    at = run_app()
    assert not at.exception
    assert any("API online" in s.value for s in at.sidebar.success)
    assert any("LangSmith: ON" in c.value for c in at.sidebar.caption)


def test_chat_question_shows_answer_sql_and_warning(fake_api):
    at = run_app()
    at.chat_input[0].set_value("How many orders?").run()
    assert not at.exception
    assert fake_api["ask"][0]["question"] == "How many orders?"
    assert any("There are 5 orders." in m.value for m in at.markdown)
    assert any("98765.43" in w.value for w in at.warning)
    assert any("SELECT COUNT" in c.value for c in at.code)


def test_clarification_flow(fake_api):
    at = run_app()
    at.chat_input[0].set_value("ambiguous").run()
    assert any("Which year?" in m.value for m in at.markdown)
    at.chat_input[0].set_value("2017").run()
    assert fake_api["ask"][1] == {"question": "ambiguous", "clarification": "2017"}
