"""evaluate.py : benchmark de l'agent sur le golden set.

Mesure principale : execution accuracy. Le SQL de référence et le SQL de l'agent sont exécutés,
puis les résultats sont comparés (peu importe l'écriture du SQL, l'ordre des lignes ou des
colonnes, ou les colonnes en plus).

Usage (depuis la racine du projet) :
    python -m agent.eval.evaluate --check-gold              # vérifie que les SQL de référence tournent
    python -m agent.eval.evaluate                           # modèle courant de .env
    python -m agent.eval.evaluate --models groq-gpt-oss-20b,gemini-flash --limit 10
Résultats : agent/eval/results/<date>.csv (résumé, lu par le dashboard) et results/details/.
"""
import argparse
import dataclasses
import decimal
import json
import os
import statistics
import time
from pathlib import Path

import pandas as pd

from agent.config import Config
from agent.graph_react_baseline import run_agent
from agent.tools import ToolContext, make_backend, run_sql

HERE = Path(__file__).parent


# ---------------------------------------------------------------- comparaison des résultats


def _norm(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (bool, int, float, decimal.Decimal)):
        return round(float(v), 2)
    return str(v)


def _column(df: pd.DataFrame, i: int) -> list:
    return sorted((_norm(v) for v in df.iloc[:, i]), key=lambda v: (v is None, str(v)))


def results_match(gold: pd.DataFrame, got: pd.DataFrame) -> bool:
    """Vrai si l'agent renvoie les mêmes données que la référence."""
    if len(gold) != len(got):
        return False
    if gold.empty:
        return True
    if got.shape[1] < gold.shape[1]:
        return False
    # chaque colonne de la référence doit exister (mêmes valeurs) dans le résultat de l'agent
    mapping, used = [], set()
    for gi in range(gold.shape[1]):
        gcol = _column(gold, gi)
        found = next((j for j in range(got.shape[1]) if j not in used and _column(got, j) == gcol), None)
        if found is None:
            return False
        used.add(found)
        mapping.append(found)
    key = lambda row: tuple((v is None, str(v)) for v in row)   # noqa: E731
    g_rows = sorted((tuple(_norm(v) for v in r) for r in gold.itertuples(index=False)), key=key)
    a_rows = sorted((tuple(_norm(r[j]) for j in mapping) for r in got.itertuples(index=False)), key=key)
    return g_rows == a_rows


# ---------------------------------------------------------------- exécution


def load_golden(path: str | None = None) -> list[dict]:
    return json.loads(Path(path or HERE / "golden_set.json").read_text(encoding="utf-8"))


def load_profiles(path: str | None = None) -> dict:
    return json.loads(Path(path or HERE / "models.json").read_text(encoding="utf-8"))


def config_for(profile: dict | None, base: Config) -> Config:
    if profile is None:
        return base
    key = os.getenv(profile["api_key_env"], "")
    if not key:
        raise SystemExit(f"Variable d'environnement {profile['api_key_env']} manquante pour {profile['model']}")
    return dataclasses.replace(base, llm_base_url=profile["base_url"], llm_model=profile["model"], llm_api_key=key)


def gold_result(cfg: Config, backend, sql: str) -> pd.DataFrame:
    ctx = ToolContext(cfg=cfg, backend=backend)
    r = run_sql(ctx, sql=sql)
    if not r.success:
        raise RuntimeError(r.result_for_llm)
    return ctx.results[r.metadata["result_id"]]


def check_gold(cfg: Config, backend, golden: list[dict]) -> int:
    bad = 0
    for q in golden:
        if q["type"] != "sql":
            continue
        try:
            df = gold_result(cfg, backend, q["gold_sql"])
            note = "OK" if len(df) else "OK mais 0 ligne (à vérifier)"
            bad += 0 if len(df) else 1
            print(f"{q['id']} {note} ({len(df)} lignes)")
        except Exception as e:   # noqa: BLE001
            bad += 1
            print(f"{q['id']} ERREUR : {str(e)[:200]}")
    print(f"\n{bad} problème(s) sur {sum(q['type'] == 'sql' for q in golden)} requêtes de référence.")
    return bad


def evaluate_question(q: dict, cfg: Config, llm, backend, gold: pd.DataFrame | None) -> dict:
    ctx = ToolContext(cfg=cfg, backend=backend)
    run = run_agent(q["question"], llm, ctx)
    ran_sql = [t for t in run.trace if t["tool"] == "run_sql" and t["success"]]
    row = {"id": q["id"], "type": q["type"], "category": q["category"], "status": run.stopped_reason,
           "steps": run.steps, "latency_s": run.latency_s,
           "tokens": run.prompt_tokens + run.completion_tokens, "passed": False, "detail": ""}
    if q["type"] == "refuse":
        row["passed"] = run.stopped_reason == "blocked" or not ran_sql
        row["detail"] = "refused" if row["passed"] else "executed SQL instead of refusing"
        return row
    if not ran_sql:
        row["detail"] = f"no successful SQL ({run.stopped_reason}): {run.answer[:120]}"
        return row
    got = ctx.results.get(ran_sql[-1].get("result_id"))
    ok = got is not None and results_match(gold, got)
    if ok and q.get("expects_chart") and not any(t.get("chart_path") for t in run.trace):
        ok, row["detail"] = False, "correct data but no chart"
    row["passed"] = ok
    row["detail"] = row["detail"] or ("match" if ok else "result differs from reference")
    return row


def summarize(name: str, backend_name: str, rows: list[dict]) -> dict:
    sql_rows = [r for r in rows if r["type"] == "sql"]
    ref_rows = [r for r in rows if r["type"] == "refuse"]
    lat = sorted(r["latency_s"] for r in rows)
    pct = lambda q: round(lat[min(len(lat) - 1, int(q * len(lat)))], 2) if lat else 0.0   # noqa: E731
    return {
        "model": name, "backend": backend_name, "n": len(rows),
        "exec_accuracy": round(sum(r["passed"] for r in sql_rows) / len(sql_rows), 3) if sql_rows else None,
        "p50_latency_s": pct(0.5), "p95_latency_s": pct(0.95),
        "avg_tokens": round(statistics.mean(r["tokens"] for r in rows)) if rows else 0,
        "refusal_rate": round(sum(r["passed"] for r in ref_rows) / len(ref_rows), 3) if ref_rows else None,
        "avg_steps": round(statistics.mean(r["steps"] for r in rows), 2) if rows else 0,
    }


def run_benchmark(base: Config, profiles: dict[str, dict | None], golden: list[dict], llm_factory=None,
                  sleep_s: float = 0.0, out_dir: str | None = None, verbose: bool = True) -> pd.DataFrame:
    from agent.llm import LLM
    llm_factory = llm_factory or LLM
    backend = make_backend(base)
    gold_cache: dict[str, pd.DataFrame] = {}
    summaries = []
    out = Path(out_dir or HERE / "results")
    (out / "details").mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    try:
        for name, profile in profiles.items():
            cfg = config_for(profile, base)
            llm = llm_factory(cfg)
            rows = []
            for q in golden:
                gold = None
                if q["type"] == "sql":
                    if q["id"] not in gold_cache:
                        gold_cache[q["id"]] = gold_result(base, backend, q["gold_sql"])
                    gold = gold_cache[q["id"]]
                try:
                    row = evaluate_question(q, cfg, llm, backend, gold)
                except Exception as e:   # noqa: BLE001
                    row = {"id": q["id"], "type": q["type"], "category": q["category"], "status": "error",
                           "steps": 0, "latency_s": 0.0, "tokens": 0, "passed": False, "detail": str(e)[:160]}
                rows.append(row)
                if verbose:
                    print(f"[{name}] {q['id']} {'PASS' if row['passed'] else 'FAIL'} "
                          f"{row['latency_s']}s {row['detail']}")
                time.sleep(sleep_s)
            pd.DataFrame(rows).to_csv(out / "details" / f"{stamp}_{name}.csv", index=False)
            summaries.append(summarize(name, cfg.sql_backend, rows))
    finally:
        if hasattr(backend, "close"):
            backend.close()
    df = pd.DataFrame(summaries)
    df.to_csv(out / f"{stamp}.csv", index=False)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", help="profils de models.json séparés par des virgules (défaut : modèle de .env)")
    ap.add_argument("--limit", type=int, help="ne passer que les N premières questions")
    ap.add_argument("--sleep", type=float, default=2.0, help="pause entre questions (limites des API gratuites)")
    ap.add_argument("--check-gold", action="store_true", help="vérifie les SQL de référence puis s'arrête")
    ap.add_argument("--golden", help="chemin d'un autre golden set")
    args = ap.parse_args()

    base = Config()
    golden = load_golden(args.golden)
    if args.check_gold:
        raise SystemExit(1 if check_gold(base, make_backend(base), golden) else 0)
    if args.limit:
        golden = golden[: args.limit]
    if args.models:
        all_profiles = load_profiles()
        names = [m.strip() for m in args.models.split(",")]
        unknown = [n for n in names if n not in all_profiles]
        if unknown:
            raise SystemExit(f"Profils inconnus : {unknown}. Disponibles : {sorted(all_profiles)}")
        profiles = {n: all_profiles[n] for n in names}
    else:
        profiles = {base.llm_model or "env": None}
    print(run_benchmark(base, profiles, golden, sleep_s=args.sleep).to_string(index=False))


if __name__ == "__main__":
    main()
