"""client.py : petit client HTTP pour l'API de l'agent (le dashboard ne parle qu'à l'API)."""
import os

import httpx

DEFAULT_URL = os.getenv("API_URL", "http://127.0.0.1:8000")


class ApiError(Exception):
    """Erreur lisible renvoyée par l'API ou impossibilité de la joindre."""


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 180.0):
        self.base_url = (base_url or DEFAULT_URL).rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            r = httpx.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
        except httpx.HTTPError as e:
            raise ApiError(f"Cannot reach the API at {self.base_url} ({type(e).__name__}). "
                           "Start it with: uvicorn api.main:app --reload") from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ApiError(f"API error {r.status_code}: {detail}")
        return r

    def get(self, path: str, **params):
        return self._request("GET", path, params=params).json()

    def post(self, path: str, payload: dict):
        return self._request("POST", path, json=payload).json()

    def image(self, path: str) -> bytes:
        return self._request("GET", path).content

    # raccourcis
    def health(self) -> dict:
        return self.get("/health")

    def ask(self, question: str, clarification: str | None = None) -> dict:
        return self.post("/ask", {"question": question, "clarification": clarification})

    def result(self, result_id: str, limit: int = 100) -> dict:
        return self.get(f"/results/{result_id}", limit=limit)

    def runs(self, limit: int = 200) -> list:
        return self.get("/runs", limit=limit)

    def stats(self) -> dict:
        return self.get("/stats")
