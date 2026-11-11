import asyncio

import pytest

from agent.mcp_backend import parse_result, run_statement

# Réponse réelle observée sur Databricks (execute_sql, COUNT(*) sur fact_orders)
REAL = {
    "statement_id": "01f1dc90",
    "status": {"state": "SUCCEEDED"},
    "manifest": {"schema": {"column_count": 1, "columns": [
        {"name": "n", "type_text": "BIGINT", "type_name": "LONG", "position": 0}]}},
    "result": {"row_count": 1, "data_typed_array": [{"values": [{"str": "99441"}]}]},
}


def test_parse_real_payload():
    df = parse_result(REAL)
    assert list(df.columns) == ["n"] and df["n"].iloc[0] == 99441


def test_parse_types_and_nulls():
    payload = {"manifest": {"schema": {"columns": [
        {"name": "m", "type_name": "STRING"}, {"name": "rev", "type_name": "DECIMAL"},
        {"name": "late", "type_name": "BOOLEAN"}, {"name": "score", "type_name": "INT"}]}},
        "result": {"data_typed_array": [
            {"values": [{"str": "2017-11"}, {"str": "1003862.14"}, {"str": "true"}, {"str": "5"}]},
            {"values": [{"str": "2017-12"}, {}, {"str": "false"}, {}]},
        ]}}
    df = parse_result(payload)
    assert df["rev"].iloc[0] == 1003862.14 and bool(df["late"].iloc[0]) is True
    assert df["score"].iloc[0] == 5
    assert df["rev"].isna().iloc[1] and df["score"].isna().iloc[1]


def test_parse_empty_result():
    payload = {"manifest": {"schema": {"columns": [{"name": "a", "type_name": "LONG"}]}}, "result": {}}
    df = parse_result(payload)
    assert df.empty and list(df.columns) == ["a"]


def fake_tool(responses):
    calls = []

    async def call(name, args):
        calls.append((name, args))
        return responses.pop(0)
    return call, calls


def test_direct_success():
    call, calls = fake_tool([REAL])
    df = asyncio.run(run_statement(call, "SELECT 1"))
    assert df["n"].iloc[0] == 99441 and calls == [("execute_sql", {"query": "SELECT 1"})]


def test_pending_then_poll():
    pending = {"statement_id": "abc", "status": {"state": "PENDING"}}
    call, calls = fake_tool([pending, pending, REAL])
    df = asyncio.run(run_statement(call, "SELECT 1", poll_every_s=0))
    assert df["n"].iloc[0] == 99441
    assert [c[0] for c in calls] == ["execute_sql", "poll_sql_result", "poll_sql_result"]
    assert calls[1][1] == {"statement_id": "abc"}


def test_failed_statement_raises_message():
    failed = {"statement_id": "x", "status": {"state": "FAILED", "error": {"message": "TABLE_NOT_FOUND"}}}
    call, _ = fake_tool([failed])
    with pytest.raises(RuntimeError, match="TABLE_NOT_FOUND"):
        asyncio.run(run_statement(call, "SELECT * FROM nope"))


def test_timeout():
    pending = {"statement_id": "abc", "status": {"state": "RUNNING"}}

    async def call(name, args):
        return pending
    with pytest.raises(TimeoutError):
        asyncio.run(run_statement(call, "SELECT 1", timeout_s=0.05, poll_every_s=0.01))
