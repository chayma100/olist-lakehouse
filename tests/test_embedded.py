from dashboard.client import ApiClient


def test_embedded_mode_serves_routes_in_process(monkeypatch):
    monkeypatch.setenv("EMBEDDED_API", "1")
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    client = ApiClient()
    assert isinstance(client.stats(), dict)
    assert client.health()["sql_backend"] in {"duckdb", "mcp", "databricks"}
