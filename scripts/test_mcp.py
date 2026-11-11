"""Teste si le serveur MCP SQL managé de Databricks est utilisable avec ton token.

Usage :  pip install mcp   puis   python scripts/test_mcp.py
Lit DATABRICKS_SERVER_HOSTNAME et DATABRICKS_TOKEN dans .env
Essaie l'ancien endpoint (/api/2.0/mcp/sql) puis le nouveau (ai-gateway).
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()
host = os.environ["DATABRICKS_SERVER_HOSTNAME"].replace("https://", "").strip("/")
token = os.environ["DATABRICKS_TOKEN"]

URLS = {
    "ancien (api/2.0/mcp/sql)": f"https://{host}/api/2.0/mcp/sql",
    "nouveau (ai-gateway)": f"https://{host}/ai-gateway/mcp-services/system.ai.dbsql",
}


async def try_url(name: str, url: str):
    # Compatible avec mcp >= 2 (streamable_http_client) et mcp 1.x (streamablehttp_client)
    from mcp import ClientSession
    try:
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        transport = streamable_http_client(
            url, http_client=create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}))
    except ImportError:
        from mcp.client.streamable_http import streamablehttp_client
        transport = streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"})

    try:
        async with transport as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"[OK]     {name} : tools = {[t.name for t in tools.tools]}")
                return True
    except BaseException as e:  # noqa: BLE001  (on veut voir toute erreur)
        sub = getattr(e, "exceptions", None)
        detail = repr(sub[0]) if sub else repr(e)
        print(f"[ÉCHEC]  {name} : {detail[:300]}")
        return False


async def main():
    for name, url in URLS.items():
        await try_url(name, url)


asyncio.run(main())
