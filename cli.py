"""Lancer l'agent en ligne de commande : python cli.py "How many orders per state?" """
import sys

from agent.config import Config
from agent.graph_react_baseline import run_agent
from agent.llm import LLM
from agent.tools import ToolContext, make_backend

cfg = Config()
backend = make_backend(cfg)
ctx = ToolContext(cfg=cfg, backend=backend, ask_fn=input)
try:
    run = run_agent(" ".join(sys.argv[1:]), LLM(cfg), ctx)
finally:
    if hasattr(backend, "close"):
        backend.close()

print(run.answer)
print(f"\n[{cfg.sql_backend} | {run.steps} steps | total {run.latency_s}s "
      f"(LLM {run.llm_time_s}s, tools {run.tools_time_s}s) | "
      f"{run.prompt_tokens}+{run.completion_tokens} tokens]")
for t in run.trace:
    print(" -", t["tool"], "OK" if t["success"] else "FAIL", f"{t['latency_s']}s", t.get("sql", ""))
    if t.get("error"):
        print("     error:", str(t["error"])[:300])
