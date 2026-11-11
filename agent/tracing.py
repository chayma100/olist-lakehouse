"""tracing.py : observabilité.

Deux niveaux, indépendants :
  1. LangSmith (optionnel) : trace chaque exécution (étapes, appels LLM, tools).
     Activé seulement si LANGSMITH_TRACING=true et LANGSMITH_API_KEY est défini.
  2. Journal local runs/runs.jsonl : une ligne par question (voir runlog.py).

Sécurité : on n'envoie à LangSmith que des données simples (question, SQL, résultats),
jamais les objets de configuration, qui contiennent la clé API et le token.
"""
import json
import os
from typing import Any, Callable

_SKIP_KEYS = {"ctx", "self", "llm", "cfg", "config", "backend"}


def enabled() -> bool:
    flag = os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "")).lower()
    key = os.getenv("LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", ""))
    return flag == "true" and bool(key)


def scrub(inputs: dict) -> dict:
    """Garde seulement les entrées simples et sérialisables."""
    clean = {}
    for k, v in (inputs or {}).items():
        if k in _SKIP_KEYS:
            continue
        try:
            json.dumps(v)
            clean[k] = v
        except (TypeError, ValueError):
            clean[k] = f"<{type(v).__name__}>"
    return clean


def trace(name: str, run_type: str = "chain") -> Callable:
    """Décorateur : trace la fonction dans LangSmith si activé, sinon ne fait rien."""
    def decorator(fn: Callable) -> Callable:
        if not enabled():
            return fn
        try:
            from langsmith import traceable
        except ImportError:
            return fn
        return traceable(name=name, run_type=run_type, process_inputs=scrub)(fn)
    return decorator


def traced_call(name: str, run_type: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Appelle fn en la traçant sous un nom choisi à l'exécution (ex. le nom du tool)."""
    return trace(name, run_type)(fn)(*args, **kwargs)
