"""Construit l'index BM25 des commentaires d'avis.

Usage (depuis la racine du projet) :
    python -m scripts.build_reviews_index                      # lit workspace.gold.fact_reviews (Databricks)
    python -m scripts.build_reviews_index --csv olist_order_reviews_dataset.csv   # ou le CSV Kaggle
Écrit data/reviews_index/index.pkl (ignoré par git). Les requêtes de test sont affichées à la fin.
"""
import argparse
import dataclasses

import pandas as pd

from agent.config import Config
from agent.reviews import DEFAULT_INDEX_DIR, ReviewIndex, build_docs

KAGGLE_COLUMNS = {"review_comment_title": "comment_title", "review_comment_message": "comment_message",
                  "review_creation_date": "review_date"}


def rows_from_databricks() -> list[dict]:
    from agent.tools import make_backend
    cfg = dataclasses.replace(Config(), sql_backend="databricks")   # le connecteur, pas MCP (résultats tronqués)
    backend = make_backend(cfg)
    try:
        table = f"{cfg.table_prefix}.fact_reviews" if cfg.table_prefix else "fact_reviews"
        df = backend.run(f"SELECT review_id, order_id, review_score, review_date, comment_title, comment_message "
                         f"FROM {table} WHERE has_comment = TRUE")
    finally:
        backend.close()
    return df.to_dict("records")


def rows_from_csv(path: str) -> list[dict]:
    return pd.read_csv(path).rename(columns=KAGGLE_COLUMNS).to_dict("records")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="CSV Kaggle des avis au lieu de Databricks")
    ap.add_argument("--out", default=DEFAULT_INDEX_DIR, help="dossier de l'index")
    args = ap.parse_args()
    rows = rows_from_csv(args.csv) if args.csv else rows_from_databricks()
    docs = build_docs(rows)
    index = ReviewIndex(docs)
    path = index.save(args.out)
    print(f"{len(rows)} lignes lues, {len(docs)} commentaires indexés -> {path}")
    for q in ("produto chegou quebrado", "atraso na entrega", "vendedor nao respondeu"):
        hits = index.search(q, k=2)
        print(f"\n[{q}]")
        for h in hits:
            print(f"  {h['score']} (note {h['review_score']}) {h['text'][:100]}")


if __name__ == "__main__":
    main()
