"""Lit le gold dans Databricks et écrit schema_description.md (pour le prompt).

Usage :  python scripts/build_schema_description.py CATALOG.SCHEMA
Exemple: python scripts/build_schema_description.py workspace.gold

Écrit aussi les noms de tables à mettre dans ALLOWED_TABLES (.env).
Ne contient aucune donnée client : seulement noms, types et 3 exemples de valeurs.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main(prefix: str) -> None:
    from databricks import sql as dbsql

    with dbsql.connect(
        server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    ) as conn, conn.cursor() as cur:
        cur.execute(f"SHOW TABLES IN {prefix}")
        tables = [r[1] for r in cur.fetchall()]
        lines = [f"Tables in {prefix}:\n"]
        for t in tables:
            cur.execute(f"DESCRIBE TABLE {prefix}.{t}")
            cols = [(r[0], r[1]) for r in cur.fetchall() if r[0] and not r[0].startswith("#")]
            cur.execute(f"SELECT COUNT(*) FROM {prefix}.{t}")
            n = cur.fetchone()[0]
            cur.execute(f"SELECT * FROM {prefix}.{t} LIMIT 3")
            rows = cur.fetchall()
            lines.append(f"## {t}  ({n} rows)")
            for i, (name, typ) in enumerate(cols):
                examples = [str(r[i])[:30] for r in rows if i < len(r) and r[i] is not None]
                lines.append(f"- {name} ({typ})  e.g. {', '.join(examples)}")
            lines.append("")
    out = "\n".join(lines)
    with open("schema_description.md", "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    print("\nALLOWED_TABLES=" + ",".join(tables))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/build_schema_description.py CATALOG.SCHEMA")
    main(sys.argv[1])
