"""runlog.py : journal local des exécutions (une ligne JSON par question).

Sert au dashboard, au benchmark et aux endpoints /runs et /stats.
"""
import json
import os
import statistics
import time
from dataclasses import asdict

from .state import AgentRun


def _path(runs_dir: str) -> str:
    return os.path.join(runs_dir, "runs.jsonl")


def write_run(run: AgentRun, runs_dir: str) -> None:
    os.makedirs(runs_dir, exist_ok=True)
    record = asdict(run)
    record["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(_path(runs_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_runs(runs_dir: str, limit: int = 50) -> list[dict]:
    path = _path(runs_dir)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    return [json.loads(line) for line in lines if line.strip()][::-1]   # plus récent d'abord


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 3)


def stats(runs_dir: str, limit: int = 500) -> dict:
    runs = read_runs(runs_dir, limit)
    if not runs:
        return {"runs": 0}
    lat = [r["latency_s"] for r in runs]
    return {
        "runs": len(runs),
        "answered_rate": round(sum(r["stopped_reason"] == "answered" for r in runs) / len(runs), 3),
        "blocked": sum(r["stopped_reason"] == "blocked" for r in runs),
        "latency_s": {"mean": round(statistics.mean(lat), 3), "p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95)},
        "avg_steps": round(statistics.mean(r["steps"] for r in runs), 2),
        "avg_tokens": round(statistics.mean(r["prompt_tokens"] + r["completion_tokens"] for r in runs)),
        "by_backend": {b: sum(r["backend"] == b for r in runs) for b in {r["backend"] for r in runs}},
    }
