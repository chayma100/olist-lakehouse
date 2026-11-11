"""Vérifie que LangSmith reçoit bien les traces.

Usage : python -m scripts.test_langsmith
Puis ouvrir https://smith.langchain.com > Tracing > ton projet (LANGSMITH_PROJECT).
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

key = os.getenv("LANGSMITH_API_KEY", "")
project = os.getenv("LANGSMITH_PROJECT", "default")
print(f"LANGSMITH_TRACING = {os.getenv('LANGSMITH_TRACING')}")
print(f"LANGSMITH_API_KEY = {'définie' if key else 'MANQUANTE'}")
print(f"LANGSMITH_PROJECT = {project}")
if os.getenv("LANGSMITH_TRACING", "").lower() != "true" or not key:
    sys.exit("Renseigne LANGSMITH_TRACING=true et LANGSMITH_API_KEY dans .env")

from langsmith import Client  # noqa: E402

from agent.tracing import trace  # noqa: E402


@trace("smoke_test", "chain")
def smoke(question: str) -> str:
    return f"echo: {question}"


smoke("hello langsmith")
client = Client()
client.flush()
time.sleep(3)
try:
    runs = list(client.list_runs(project_name=project, limit=3))
except Exception as e:   # noqa: BLE001
    sys.exit(f"Trace envoyée mais le projet n'a pas pu être lu : {e}")
print("OK, dernières traces du projet :", [r.name for r in runs])
print("Ouvre LangSmith > Tracing pour voir la trace 'smoke_test'.")
