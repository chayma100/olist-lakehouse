from agent.guardrails import validate_sql

ALLOWED = ["fact_orders", "dim_customers"]


def ok(sql):
    return validate_sql(sql, ALLOWED, max_rows=100)


def test_simple_select_gets_limit():
    r = ok("SELECT * FROM fact_orders")
    assert r.ok and "LIMIT 100" in r.sql


def test_existing_small_limit_kept():
    r = ok("SELECT * FROM fact_orders LIMIT 5")
    assert r.ok and "LIMIT 5" in r.sql


def test_big_limit_capped():
    r = ok("SELECT * FROM fact_orders LIMIT 100000")
    assert r.ok and "LIMIT 100" in r.sql and "100000" not in r.sql


def test_join_and_cte_allowed():
    r = ok("WITH t AS (SELECT customer_id FROM fact_orders) "
           "SELECT c.customer_id FROM t JOIN dim_customers c ON c.customer_id = t.customer_id")
    assert r.ok


def test_qualified_name_allowed():
    assert ok("SELECT * FROM main.gold.fact_orders").ok


def test_union_allowed():
    assert ok("SELECT customer_id FROM fact_orders UNION SELECT customer_id FROM dim_customers").ok


def test_rejects_write_statements():
    for q in ["DROP TABLE fact_orders", "DELETE FROM fact_orders",
              "INSERT INTO fact_orders VALUES (1)", "UPDATE fact_orders SET a=1",
              "CREATE TABLE x AS SELECT 1"]:
        assert not ok(q).ok, q


def test_rejects_multiple_statements():
    assert not ok("SELECT 1 FROM fact_orders; DROP TABLE fact_orders").ok


def test_rejects_unknown_table():
    r = ok("SELECT * FROM silver_orders")
    assert not r.ok and "not allowed" in r.reason


def test_rejects_unknown_table_in_subquery():
    assert not ok("SELECT * FROM fact_orders WHERE x IN (SELECT x FROM secret)").ok


def test_rejects_garbage_and_empty():
    assert not ok("").ok
    assert not ok("hello world this is not sql").ok


def test_input_guard_blocks_ddl_requests_but_not_reads():
    from agent.guardrails import input_guard
    for q in ["Create a new table called top_customers with the 100 best customers.",
              "create table x as select 1", "Please make a view named v", "Can you build a new schema?"]:
        assert not input_guard(q).ok, q
    for q in ["Make a table of the top categories", "Create a bar chart of orders per state",
              "Show me a table of revenue per month"]:
        assert input_guard(q).ok, q
