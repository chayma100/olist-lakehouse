"""Explore le serveur MCP SQL de Databricks : schémas des tools + une requête test.

Usage :  python scripts/explore_mcp.py
Affiche des informations techniques (pas de secret). Envoie-moi la sortie.
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()
host = os.environ["DATABRICKS_SERVER_HOSTNAME"].replace("https://", "").strip("/")
token = os.environ["DATABRICKS_TOKEN"]
URL = f"https://{host}/ai-gateway/mcp-services/system.ai.dbsql"
QUERY = "SELECT COUNT(*) AS n FROM workspace.gold.fact_orders"


def show(title, obj):
    print(f"\n===== {title} =====")
    try:
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str)[:3000])
    except Exception:
        print(str(obj)[:3000])


async def main():
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    transport = streamable_http_client(
        URL, http_client=create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}))
    async with transport as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            tools = await session.list_tools()
            for t in tools.tools:
                show(f"TOOL {t.name}", t.model_dump(exclude_none=True))

            result = await session.call_tool("execute_sql", {"query": QUERY})
            show("RESULTAT execute_sql (brut)", result.model_dump())


asyncio.run(main())
