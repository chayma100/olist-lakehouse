"""Chaque SQL de référence du golden set doit être valide face au schéma documenté dans le prompt.

On crée des tables DuckDB VIDES à partir de DEFAULT_SCHEMA : si une requête cite une colonne ou
une table inexistante, ou applique une fonction à un mauvais type, elle échoue ici (en CI, sans
Databricks). Cela ne remplace pas `python -m agent.eval.evaluate --check-gold` sur les vraies données.
"""
import re

import duckdb
import pytest

from agent.eval import evaluate as ev
from agent.prompts import DEFAULT_SCHEMA

NUMERIC_HINTS = ("revenue", "total", "price", "freight", "value", "score", "count", "days", "_g",
                 "_cm", "pct", "share", "rate", "avg", "installments", "order", "order_item_id",
                 "step", "group_order", "item_count")


def _split_top_level(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def schema_tables() -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    current = None
    for line in DEFAULT_SCHEMA.splitlines():
        m = re.match(r"^([a-z_]+)\s+\(", line)
        if m:
            current = m.group(1)
            tables[current] = []
        elif current and line.startswith("  "):
            for item in _split_top_level(line.strip()):
                c = re.match(r"([a-z][a-z_0-9]*)", item.strip())
                if c:
                    tables[current].append(c.group(1))
        elif not line.strip():
            current = None
    return tables


def col_type(name: str) -> str:
    if name.startswith(("is_", "has_")) or name == "category_unknown":
        return "BOOLEAN"
    if name in ("order_date", "review_date") or name.endswith(("_at", "_timestamp")) or "_date" in name:
        return "TIMESTAMP"
    if name.endswith(("_id", "_month", "_state", "_city", "state", "city", "category", "status",
                      "category_pt", "payment_types", "delay_group", "comment_title",
                      "comment_message", "zip_prefix")) or name in ("order_status", "delivery_state"):
        return "VARCHAR"
    if any(h in name for h in NUMERIC_HINTS):
        return "DOUBLE"
    return "VARCHAR"


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    for table, cols in schema_tables().items():
        c.execute(f"CREATE TABLE {table} (" + ", ".join(f"{col} {col_type(col)}" for col in dict.fromkeys(cols)) + ")")
    return c


def test_schema_parser_finds_the_documented_tables():
    t = schema_tables()
    assert {"fact_orders", "fact_reviews", "dim_sellers", "kpi_monthly_revenue"} <= set(t)
    assert "is_late" in t["fact_orders"] and "review_score" in t["fact_reviews"]


def test_all_gold_sql_binds_against_documented_schema(con):
    problems = []
    for q in ev.load_golden():
        if q["type"] != "sql":
            continue
        try:
            con.execute(q["gold_sql"]).fetchall()
        except Exception as e:  # noqa: BLE001
            problems.append(f"{q['id']}: {str(e).splitlines()[0][:140]}")
    assert not problems, "\n".join(problems)
