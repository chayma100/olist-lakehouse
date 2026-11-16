from fastapi.testclient import TestClient

from api.main import create_app


def test_open_when_no_key_configured(monkeypatch):
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    assert TestClient(create_app()).get("/stats").status_code != 401


def test_key_required_when_configured(monkeypatch):
    monkeypatch.setenv("API_ACCESS_KEY", "secret")
    c = TestClient(create_app())
    assert c.get("/health").status_code != 401          # sonde de l'hébergeur
    assert c.get("/stats").status_code == 401
    assert c.get("/stats", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/stats", headers={"X-API-Key": "secret"}).status_code != 401
