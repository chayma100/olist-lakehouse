"""mcp_backend.py : exécuter le SQL via le serveur MCP managé de Databricks.

Même interface que les autres backends : run(sql) -> DataFrame.

Le serveur expose deux tools :
  - execute_sql(query)            lance la requête (réponse directe si rapide)
  - poll_sql_result(statement_id) à rappeler tant que la requête est en cours

Une session MCP reste ouverte dans un thread dédié (se connecter coûte du temps).
"""
import asyncio
import json
import threading
import time
from concurrent.futures import Future
from typing import Any, Awaitable, Callable

import pandas as pd

from .config import Config

PENDING_STATES = {"PENDING", "RUNNING"}
FAILED_STATES = {"FAILED", "CANCELED", "CLOSED"}
INT_TYPES = {"LONG", "INT", "SHORT", "BYTE"}
FLOAT_TYPES = {"DOUBLE", "FLOAT", "DECIMAL"}

CallTool = Callable[[str, dict], Awaitable[dict]]


# ---------------------------------------------------------------- lecture des réponses


def _cell(item: Any, type_name: str) -> Any:
    """Une valeur du format {"str": "99441"} -> valeur Python typée."""
    if isinstance(item, dict):
        if not item:
            return None
        value = next(iter(item.values()))
    else:
        value = item
    if value is None:
        return None
    try:
        if type_name in INT_TYPES:
            return int(value)
        if type_name in FLOAT_TYPES:
            return float(value)
        if type_name == "BOOLEAN":
            return value if isinstance(value, bool) else str(value).lower() == "true"
    except (TypeError, ValueError):
        return value
    return value


def parse_result(payload: dict) -> pd.DataFrame:
    """Transforme la réponse du serveur MCP en DataFrame."""
    columns = payload.get("manifest", {}).get("schema", {}).get("columns") or []
    names = [c["name"] for c in columns]
    types = [c.get("type_name", "STRING") for c in columns]
    rows = []
    for row in (payload.get("result") or {}).get("data_typed_array") or []:
        values = row.get("values", [])
        rows.append([_cell(values[i] if i < len(values) else None, types[i])
                     for i in range(len(names))])
    return pd.DataFrame(rows, columns=names)


def _payload(result: Any) -> dict:
    """Extrait le JSON d'une réponse de tool MCP."""
    if getattr(result, "is_error", False):
        text = " ".join(getattr(c, "text", "") for c in result.content)
        raise RuntimeError(text or "MCP tool error")
    if getattr(result, "structured_content", None):
        return result.structured_content
    text = "".join(getattr(c, "text", "") for c in result.content)
    return json.loads(text)


async def run_statement(call_tool: CallTool, sql: str, timeout_s: float = 120,
                        poll_every_s: float = 1.0) -> pd.DataFrame:
    """Lance la requête puis attend la fin (poll_sql_result) si elle est en cours."""
    payload = await call_tool("execute_sql", {"query": sql})
    deadline = time.monotonic() + timeout_s
    while True:
        state = (payload.get("status") or {}).get("state", "SUCCEEDED")
        if state == "SUCCEEDED":
            return parse_result(payload)
        if state in FAILED_STATES:
            err = (payload.get("status") or {}).get("error") or {}
            raise RuntimeError(err.get("message") or f"Statement {state}")
        if state not in PENDING_STATES:
            raise RuntimeError(f"Unexpected statement state: {state}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Query still {state} after {timeout_s}s")
        await asyncio.sleep(poll_every_s)
        payload = await call_tool("poll_sql_result", {"statement_id": payload["statement_id"]})


# ---------------------------------------------------------------- backend


class McpBackend:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.url = (f"https://{cfg.databricks_hostname.replace('https://', '').strip('/')}"
                    "/ai-gateway/mcp-services/system.ai.dbsql")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    # -- thread + session persistante
    def _start(self) -> None:
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=60):
            raise TimeoutError("Could not open the MCP session in time.")
        if self._error:
            raise RuntimeError(f"MCP connection failed: {self._error!r}")

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._worker())
        except BaseException as e:  # noqa: BLE001
            self._error = e
            self._ready.set()
        finally:
            self._loop.close()

    async def _worker(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        self._queue = asyncio.Queue()
        http_client = create_mcp_http_client(
            headers={"Authorization": f"Bearer {self.cfg.databricks_token}"})
        async with streamable_http_client(self.url, http_client=http_client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()

                async def call_tool(name: str, args: dict) -> dict:
                    return _payload(await session.call_tool(name, args))

                self._ready.set()
                while True:
                    item = await self._queue.get()
                    if item is None:
                        return
                    sql, fut = item
                    try:
                        fut.set_result(await run_statement(call_tool, sql, self.cfg.mcp_timeout_s))
                    except BaseException as e:  # noqa: BLE001
                        fut.set_exception(e)

    def run(self, sql: str) -> pd.DataFrame:
        if self._thread is None or not self._thread.is_alive():
            self._start()
        fut: Future = Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (sql, fut))
        return fut.result(timeout=self.cfg.mcp_timeout_s + 30)

    def close(self) -> None:
        if self._thread and self._thread.is_alive() and self._loop:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
