"""Garde-fous sur le golden set et la logique de notation (aucun secret, aucun réseau)."""
from types import SimpleNamespace

import pytest

from agent.eval import evaluate as ev

VALID_TYPES = {"sql", "refuse", "review", "unanswerable"}


@pytest.fixture(scope="module")
def golden():
    return ev.load_golden()


# ---------------------------------------------------------------- intégrité du jeu de test


def test_ids_are_unique(golden):
    ids = [q["id"] for q in golden]
    assert len(ids) == len(set(ids))


def test_every_question_is_well_formed(golden):
    for q in golden:
        assert q["type"] in VALID_TYPES, q["id"]
        assert q["question"].strip(), q["id"]
        assert q["category"], q["id"]
        assert q.get("split", "dev") in {"dev", "test"}, q["id"]
        if q["type"] == "sql":
            sql = q["gold_sql"].lstrip().upper()
            assert sql.startswith(("SELECT", "WITH")), f"{q['id']} : la référence doit être un SELECT"
        if q["type"] == "unanswerable":
            assert q.get("must_contain_any"), f"{q['id']} : mots-clés manquants"


def test_both_splits_are_populated(golden):
    splits = {q.get("split", "dev") for q in golden}
    assert splits == {"dev", "test"}


# ---------------------------------------------------------------- statistiques


def test_wilson_interval_matches_known_values():
    low, high = ev.wilson(25, 28)
    assert 0.72 < low < 0.74 and 0.955 < high < 0.97
    assert ev.wilson(0, 0) == (None, None)


def test_wilson_interval_narrows_with_more_questions():
    small = ev.wilson(25, 28)
    big = ev.wilson(54, 60)
    assert (big[1] - big[0]) < (small[1] - small[0])


def _row(**kw):
    base = {"id": "x", "type": "sql", "category": "simple", "status": "answered", "steps": 2,
            "latency_s": 5.0, "tokens": 1000, "passed": True, "detail": ""}
    return {**base, **kw}


def test_summarize_reports_confidence_interval_and_new_rates():
    rows = [_row(id=f"q{i}", passed=i < 8) for i in range(10)]
    rows += [_row(id="r1", type="refuse", category="guardrail", latency_s=0.0, steps=0),
             _row(id="rv1", type="review", category="review_tool", passed=False),
             _row(id="u1", type="unanswerable", category="unanswerable")]
    s = ev.summarize("m", "mcp", rows)
    assert s["exec_accuracy"] == 0.8 and s["exec_n"] == 10
    assert s["exec_ci95_low"] < 0.8 < s["exec_ci95_high"]
    assert s["review_tool_rate"] == 0.0 and s["unanswerable_rate"] == 1.0


def test_sql_latency_excludes_refusals_and_technical_errors():
    rows = [_row(id="a", latency_s=10.0), _row(id="b", latency_s=20.0),
            _row(id="c", status="error", latency_s=0.0, passed=False),
            _row(id="r1", type="refuse", category="guardrail", latency_s=0.0, steps=0)]
    s = ev.summarize("m", "mcp", rows)
    assert s["p50_latency_sql_s"] == 20.0       # médiane des seules questions SQL traitées
    assert s["p50_latency_s"] < s["p50_latency_sql_s"]   # l'ancienne médiane était tirée vers le bas par les 0 s


def test_summarize_by_category_sorts_weakest_first():
    rows = [_row(id="a", category="chart", passed=False), _row(id="b", category="chart", passed=True),
            _row(id="c", category="simple", passed=True)]
    out = ev.summarize_by_category(rows)
    assert list(out["category"]) == ["chart", "simple"]


# ---------------------------------------------------------------- notation par type (faux agent)


def _fake_run(answer="", trace=None, stopped="answered"):
    return SimpleNamespace(answer=answer, trace=trace or [], stopped_reason=stopped, steps=1,
                           latency_s=1.0, prompt_tokens=10, completion_tokens=5)


def _evaluate(monkeypatch, q, run):
    monkeypatch.setattr(ev, "run_agent", lambda question, llm, ctx: run)
    return ev.evaluate_question(q, cfg=None, llm=None, backend=None, gold=None)


def test_refusal_fails_when_a_secret_leaks(monkeypatch):
    q = {"id": "r", "type": "refuse", "category": "guardrail", "question": "?", "must_not_contain": ["gsk_"]}
    ok = _evaluate(monkeypatch, q, _fake_run("I can't share credentials."))
    leak = _evaluate(monkeypatch, q, _fake_run("Sure: gsk_abc123"))
    assert ok["passed"] and not leak["passed"] and "leaked" in leak["detail"]


def test_refusal_fails_when_sql_was_executed(monkeypatch):
    q = {"id": "r", "type": "refuse", "category": "guardrail", "question": "?"}
    trace = [{"tool": "run_sql", "success": True, "result_id": "r_1"}]
    assert not _evaluate(monkeypatch, q, _fake_run("done", trace))["passed"]
    assert _evaluate(monkeypatch, q, _fake_run("blocked", [], stopped="blocked"))["passed"]


def test_review_question_needs_a_successful_search_reviews_call(monkeypatch):
    q = {"id": "rv", "type": "review", "category": "review_tool", "question": "?"}
    used = [{"tool": "search_reviews", "success": True}]
    failed = [{"tool": "search_reviews", "success": False}]
    assert _evaluate(monkeypatch, q, _fake_run("Customers mention delays.", used))["passed"]
    assert not _evaluate(monkeypatch, q, _fake_run("Customers mention delays.", failed))["passed"]
    assert not _evaluate(monkeypatch, q, _fake_run("", used))["passed"]


def test_unanswerable_question_needs_the_limit_to_be_stated(monkeypatch):
    q = {"id": "u", "type": "unanswerable", "category": "unanswerable", "question": "?",
         "must_contain_any": ["not available", "no data"]}
    assert _evaluate(monkeypatch, q, _fake_run("That data is not available in the warehouse."))["passed"]
    assert not _evaluate(monkeypatch, q, _fake_run("The margin is 23.4%."))["passed"]


# ---------------------------------------------------------------- erreurs techniques (quota 429, etc.)


def test_technical_error_is_not_counted_as_a_successful_refusal(monkeypatch):
    q = {"id": "r", "type": "refuse", "category": "guardrail", "question": "?"}
    row = _evaluate(monkeypatch, q, _fake_run("RateLimitError 429", [], stopped="error"))
    assert row["tech_error"] and not row["passed"]
    assert "technical error" in row["detail"]


def test_retry_recovers_from_a_transient_error(monkeypatch):
    calls = []

    def flaky(question, llm, ctx):
        calls.append(1)
        return _fake_run("", [], stopped="error") if len(calls) == 1 else _fake_run(
            "Customers mention delays.", [{"tool": "search_reviews", "success": True}])

    monkeypatch.setattr(ev, "run_agent", flaky)
    monkeypatch.setattr(ev.time, "sleep", lambda s: None)
    q = {"id": "rv", "type": "review", "category": "review_tool", "question": "?"}
    row = ev.evaluate_question(q, cfg=None, llm=None, backend=None, gold=None, retries=2, backoff_s=0)
    assert row["passed"] and row["retries"] == 1 and not row["tech_error"]


def test_retry_gives_up_after_the_limit(monkeypatch):
    monkeypatch.setattr(ev, "run_agent", lambda question, llm, ctx: _fake_run("429", [], stopped="error"))
    monkeypatch.setattr(ev.time, "sleep", lambda s: None)
    q = {"id": "s", "type": "sql", "category": "simple", "question": "?", "gold_sql": "SELECT 1"}
    row = ev.evaluate_question(q, cfg=None, llm=None, backend=None, gold=None, retries=2, backoff_s=0)
    assert row["tech_error"] and row["retries"] == 2 and not row["passed"]


def test_summary_separates_technical_errors_from_wrong_answers():
    rows = [_row(id="a", passed=True), _row(id="b", passed=False),
            _row(id="c", passed=False, status="error", tech_error=True),
            _row(id="d", passed=False, status="error", tech_error=True),
            _row(id="r1", type="refuse", category="guardrail", passed=True),
            _row(id="r2", type="refuse", category="guardrail", passed=False, tech_error=True)]
    s = ev.summarize("m", "mcp", rows)
    assert s["exec_accuracy"] == 0.25                 # 1 réussite sur 4 questions SQL
    assert s["exec_accuracy_excl_tech"] == 0.5        # 1 sur 2 hors erreurs techniques
    assert s["tech_errors"] == 3
    assert s["refusal_rate"] == 0.5 and s["refusal_rate_excl_tech"] == 1.0