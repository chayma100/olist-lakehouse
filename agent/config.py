"""config.py : tous les réglages au même endroit (lus depuis .env)."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip().lower() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass
class Config:
    # --- LLM (API compatible OpenAI : la plupart des providers gratuits l'offrent)
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""), repr=False)
    llm_model: str = os.getenv("LLM_MODEL", "")
    temperature: float = 0.0

    # --- Limites de la boucle
    max_steps: int = 8
    max_rows: int = 100        # LIMIT forcé sur chaque requête
    max_tool_calls: int = 12   # budget : nombre total d'appels de tools par question
    max_tokens_per_run: int = 60000  # budget : tokens (prompt + réponse) par question
    preview_rows: int = 30     # lignes montrées au LLM

    # --- Données : noms de tables gold autorisées (sans catalogue/schéma)
    allowed_tables: list[str] = field(
        default_factory=lambda: _list(
            "ALLOWED_TABLES",
            "fact_orders,fact_order_items,fact_reviews,fact_order_payments,"
            "dim_customers,dim_products,dim_sellers,"
            "kpi_category_revenue,kpi_monthly_category_revenue,kpi_monthly_revenue,"
            "kpi_delay_vs_review,kpi_state_delivery",
        )
    )
    # "databricks" (connecteur), "mcp" (serveur MCP managé) ou "duckdb"
    sql_backend: str = os.getenv("SQL_BACKEND", "duckdb")
    duckdb_path: str = os.getenv("DUCKDB_PATH", ":memory:")
    databricks_hostname: str = os.getenv("DATABRICKS_SERVER_HOSTNAME", "")
    databricks_http_path: str = os.getenv("DATABRICKS_HTTP_PATH", "")
    databricks_token: str = field(default_factory=lambda: os.getenv("DATABRICKS_TOKEN", ""), repr=False)
    # préfixe ajouté aux tables, ex. "main.gold" (catalogue.schéma)
    table_prefix: str = os.getenv("TABLE_PREFIX", "workspace.gold")

    mcp_timeout_s: float = 120   # attente max d'une requête via MCP

    output_dir: str = os.getenv("OUTPUT_DIR", "outputs")
    runs_dir: str = os.getenv("RUNS_DIR", "runs")   # journal des exécutions (JSONL)
    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8501"
        ).split(",") if o.strip()])
