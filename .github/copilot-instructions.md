# Instructions pour GitHub Copilot (projet Olist Azure Lakehouse)

## Contexte
- Projet d'apprentissage : pipeline ETL (Bronze, Silver, Gold) sur le dataset Olist, puis Azure, Databricks et un agent IA text-to-SQL.
- Je suis débutante en ETL, Azure, Databricks et LangChain. Explique simplement, en français.

## Stack
- Python 3.11, DuckDB (dialecte SQL DuckDB), dbt-duckdb en local.
- Plus tard : PySpark / Delta sur Databricks, Azure Data Lake Storage Gen2, Azure Data Factory.
- Agent : LangChain / LangGraph, sqlglot pour valider le SQL.

## Règles
- Ne jamais modifier ni supprimer les fichiers de data/raw.
- Les requêtes de l'agent doivent être en lecture seule (SELECT uniquement, avec LIMIT).
- Aucun secret en dur : utiliser des variables d'environnement (fichier .env).
- Écrire des petites fonctions, avec des commentaires en français qui expliquent le POURQUOI.
- Quand tu proposes du code, explique d'abord l'idée en 2-3 phrases.
- Demande avant d'ajouter une nouvelle dépendance.
- Propose un test simple quand c'est pertinent.
