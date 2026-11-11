"""Teste la connexion à Databricks et l'accès au gold.

Usage :  python scripts/test_connection.py
Lit DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN dans .env
"""
import os

from dotenv import load_dotenv

load_dotenv()

missing = [k for k in ("DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN")
           if not os.getenv(k)]
if missing:
    raise SystemExit(f"Variables manquantes dans .env : {', '.join(missing)}")

from databricks import sql

with sql.connect(
    server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
    http_path=os.environ["DATABRICKS_HTTP_PATH"],
    access_token=os.environ["DATABRICKS_TOKEN"],
) as conn, conn.cursor() as cur:
    print("Connexion OK")
    cur.execute("SHOW TABLES IN workspace.gold")
    print("Tables gold :", sorted(r[1] for r in cur.fetchall()))
    cur.execute("SELECT COUNT(*) FROM workspace.gold.fact_orders")
    print("Lignes dans fact_orders :", cur.fetchone()[0], "(attendu : 99441)")
