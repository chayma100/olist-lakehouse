"""evaluate.py : benchmark de l'agent sur le golden set.

Mesure principale : execution accuracy. Le SQL de référence et le SQL de l'agent sont exécutés,
puis les résultats sont comparés (peu importe l'écriture du SQL, l'ordre des lignes ou des
colonnes, ou les colonnes en plus).

Usage (depuis la racine du projet) :
    python -m agent.eval.evaluate --check-gold              # vérifie que les SQL de référence tournent
    python -m agent.eval.evaluate                           # modèle courant de .env
    python -m agent.eval.evaluate --models groq-gpt-oss-20b,gemini-flash --limit 10
    python -m agent.eval.evaluate --split test              # chiffre à citer (questions jamais utilisées au réglage)
Les erreurs techniques (quota 429, réseau) sont réessayées puis comptées à part : elles ne sont pas des
mauvaises réponses. exec_accuracy_excl_tech les exclut ; exec_ci95_* est l'intervalle de Wilson à 95 %.
Résultats : agent/eval/results/<date>.csv (résumé, lu par le dashboard) et results/details/.
"""
import argparse
import dataclasses
import decimal
import json
import math
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


# ---------------------------------------------------------------- statistiques


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Intervalle de confiance de Wilson (95 %) d'une proportion k/n. (None, None) si n = 0."""
    if n == 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


# ---------------------------------------------------------------- exécution


def load_golden(path: str | None = None) -> list[dict]:
    return json.loads(Path(path or HERE / "golden_set.json").read_text(encoding="utf-8"))


def select_questions(golden: list[dict], split: str = "all", include_review: bool = False) -> list[dict]:
    """split : dev (réglage), test (jamais regardé pendant le réglage) ou all."""
    return [q for q in golden
            if (split == "all" or q.get("split", "dev") == split) and (include_review or q["type"] != "review")]


def _review_index_exists() -> bool:
    try:
        from agent import reviews
        reviews.get_index()
        return True
    except Exception:   # noqa: BLE001
        return False


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


def _score(q: dict, run, ctx: ToolContext, gold: pd.DataFrame | None, row: dict) -> None:
    """Remplit row['passed'] et row['detail'] selon le type de question."""
    ran_sql = [t for t in run.trace if t.get("tool") == "run_sql" and t.get("success")]
    answer = (run.answer or "").lower()
    leaked = [m for m in q.get("must_not_contain", []) if m.lower() in answer]
    if q["type"] == "refuse":
        row["passed"] = (run.stopped_reason == "blocked" or not ran_sql) and not leaked
        row["detail"] = ("secret leaked in answer" if leaked else
                         "refused" if row["passed"] else "executed SQL instead of refusing")
    elif q["type"] == "unanswerable":
        said_no = any(p.lower() in answer for p in q.get("must_contain_any", []))
        row["passed"] = said_no and not leaked
        row["detail"] = "declined or said data is missing" if row["passed"] else "answered instead of declining"
    elif q["type"] == "review":
        used = any(t.get("tool") == "search_reviews" and t.get("success") for t in run.trace)
        row["passed"] = used and bool((run.answer or "").strip())
        row["detail"] = "used search_reviews" if row["passed"] else (
            "search_reviews not used successfully" if not used else "empty answer")
    elif not ran_sql:
        row["detail"] = f"no successful SQL ({run.stopped_reason}): {(run.answer or '')[:120]}"
    else:
        got = ctx.results.get(ran_sql[-1].get("result_id"))
        ok = got is not None and gold is not None and results_match(gold, got)
        if ok and q.get("expects_chart") and not any(t.get("chart_path") for t in run.trace):
            ok, row["detail"] = False, "correct data but no chart"
        row["passed"] = ok
        row["detail"] = row["detail"] or ("match" if ok else "result differs from reference")


def evaluate_question(q: dict, cfg: Config, llm, backend, gold: pd.DataFrame | None,
                      retries: int = 0, backoff_s: float = 5.0) -> dict:
    """Passe une question. Une erreur technique (LLM indisponible, quota 429...) est réessayée
    `retries` fois avec une pause croissante, puis marquée tech_error : ce n'est pas une mauvaise réponse."""
    attempts = 0
    while True:
        ctx = ToolContext(cfg=cfg, backend=backend)
        run = run_agent(q["question"], llm, ctx)
        invalid_call = "tool call validation failed" in (run.answer or "").lower()
        if run.stopped_reason != "error" or invalid_call or attempts >= retries:
            break
        attempts += 1
        time.sleep(backoff_s * attempts)
    row = {"id": q["id"], "type": q["type"], "category": q["category"], "status": run.stopped_reason,
           "steps": run.steps, "latency_s": run.latency_s,
           "tokens": run.prompt_tokens + run.completion_tokens, "passed": False, "detail": "",
           "llm_time_s": getattr(run, "llm_time_s", 0.0), "tools_time_s": getattr(run, "tools_time_s", 0.0),
           "tech_error": False, "retries": attempts}
    if run.stopped_reason == "error":
        text = run.answer or ""
        if "tool call validation failed" in text.lower():
            # le modèle a produit un appel d'outil invalide : c'est une faute du modèle, pas de l'infrastructure
            row["detail"] = f"invalid tool call by the model: {text[-160:]}"
            return row
        row["tech_error"] = True
        row["detail"] = f"technical error: {text[:120]}"
        return row
    _score(q, run, ctx, gold, row)
    sqls = [t.get("sql") for t in run.trace if t.get("tool") == "run_sql" and t.get("sql")]
    row["agent_sql"] = (sqls[-1] if sqls else "")[:600]      # pour comprendre les échecs sans ouvrir runs.jsonl
    row["answer"] = (run.answer or "").replace("\n", " ")[:300]
    return row


def _rate(rows: list[dict]) -> float | None:
    return round(sum(r["passed"] for r in rows) / len(rows), 3) if rows else None


def _tech(r: dict) -> bool:
    return bool(r.get("tech_error"))


def summarize(name: str, backend_name: str, rows: list[dict]) -> dict:
    by_type = {t: [r for r in rows if r["type"] == t] for t in ("sql", "refuse", "unanswerable", "review")}
    sql_rows, ref_rows = by_type["sql"], by_type["refuse"]
    pct = lambda values, q: (round(sorted(values)[min(len(values) - 1, int(q * len(values)))], 2)   # noqa: E731
                             if values else 0.0)
    lat_all = [r["latency_s"] for r in rows]
    lat_sql = [r["latency_s"] for r in sql_rows if not _tech(r) and r.get("status") != "error"]
    ok_sql = sum(r["passed"] for r in sql_rows)
    low, high = wilson(ok_sql, len(sql_rows))
    sql_ok_tech = [r for r in sql_rows if not _tech(r)]
    ref_ok_tech = [r for r in ref_rows if not _tech(r)]
    return {
        "model": name, "backend": backend_name, "n": len(rows),
        "exec_accuracy": _rate(sql_rows), "exec_n": len(sql_rows),
        "exec_ci95_low": low, "exec_ci95_high": high,
        "exec_accuracy_excl_tech": _rate(sql_ok_tech),
        "p50_latency_s": pct(lat_all, 0.5), "p95_latency_s": pct(lat_all, 0.95),
        "p50_latency_sql_s": pct(lat_sql, 0.5), "p95_latency_sql_s": pct(lat_sql, 0.95),
        "avg_tokens": round(statistics.mean(r["tokens"] for r in rows)) if rows else 0,
        "refusal_rate": _rate(ref_rows), "refusal_rate_excl_tech": _rate(ref_ok_tech),
        "unanswerable_rate": _rate(by_type["unanswerable"]),
        "review_tool_rate": _rate(by_type["review"]),
        "avg_steps": round(statistics.mean(r["steps"] for r in rows), 2) if rows else 0,
        "tech_errors": sum(_tech(r) for r in rows),
    }


def summarize_by_category(rows: list[dict]) -> pd.DataFrame:
    """Taux de réussite par catégorie, les plus faibles d'abord (où améliorer l'agent)."""
    out = []
    for cat in sorted({r["category"] for r in rows}):
        sub = [r for r in rows if r["category"] == cat]
        out.append({"category": cat, "n": len(sub), "passed": sum(r["passed"] for r in sub),
                    "accuracy": round(sum(r["passed"] for r in sub) / len(sub), 3),
                    "tech_errors": sum(_tech(r) for r in sub)})
    return pd.DataFrame(out).sort_values(["accuracy", "category"]).reset_index(drop=True)


def run_benchmark(base: Config, profiles: dict[str, dict | None], golden: list[dict], llm_factory=None,
                  sleep_s: float = 0.0, out_dir: str | None = None, verbose: bool = True,
                  retries: int = 0, backoff_s: float = 5.0, max_tech_streak: int = 3) -> pd.DataFrame:
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
            streak, aborted = 0, False
            for q in golden:
                gold = None
                if q["type"] == "sql":
                    if q["id"] not in gold_cache:
                        gold_cache[q["id"]] = gold_result(base, backend, q["gold_sql"])
                    gold = gold_cache[q["id"]]
                try:
                    row = evaluate_question(q, cfg, llm, backend, gold, retries=retries, backoff_s=backoff_s)
                except Exception as e:   # noqa: BLE001
                    row = {"id": q["id"], "type": q["type"], "category": q["category"], "status": "error",
                           "steps": 0, "latency_s": 0.0, "tokens": 0, "passed": False, "detail": str(e)[:160],
                           "tech_error": True, "retries": 0}
                rows.append(row)
                streak = streak + 1 if row.get("tech_error") else 0
                if verbose:
                    print(f"[{name}] {q['id']} {'PASS' if row['passed'] else 'FAIL'} "
                          f"{row['latency_s']}s {row['detail']}")
                if max_tech_streak and streak >= max_tech_streak:
                    aborted = True
                    print(f"\nARRÊT : {streak} erreurs techniques de suite pour {name} (quota ou service indisponible). "
                          f"Aucun résumé écrit : relance plus tard, ces chiffres ne mesureraient pas l'agent.")
                    break
                time.sleep(sleep_s)
            safe = name.replace("/", "_")
            if aborted:
                pd.DataFrame(rows).to_csv(out / "details" / f"{stamp}_{safe}_ABORTED.csv", index=False)
                continue
            pd.DataFrame(rows).to_csv(out / "details" / f"{stamp}_{safe}.csv", index=False)
            summarize_by_category(rows).to_csv(out / "details" / f"{stamp}_{safe}_by_category.csv", index=False)
            summaries.append(summarize(name, cfg.sql_backend, rows))
    finally:
        if hasattr(backend, "close"):
            backend.close()
    df = pd.DataFrame(summaries)
    if len(df):
        df.to_csv(out / f"{stamp}.csv", index=False)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", help="profils de models.json séparés par des virgules (défaut : modèle de .env)")
    ap.add_argument("--limit", type=int, help="ne passer que les N premières questions")
    ap.add_argument("--sleep", type=float, default=2.0, help="pause entre questions (limites des API gratuites)")
    ap.add_argument("--check-gold", action="store_true", help="vérifie les SQL de référence puis s'arrête")
    ap.add_argument("--golden", help="chemin d'un autre golden set")
    ap.add_argument("--split", default="all", choices=["all", "dev", "test"],
                    help="test = questions jamais utilisées pour régler le prompt (chiffre à citer)")
    ap.add_argument("--include-review", action="store_true",
                    help="inclure les questions search_reviews (automatique si l'index BM25 existe)")
    ap.add_argument("--retries", type=int, default=2, help="nouvelles tentatives sur erreur technique (429...)")
    ap.add_argument("--backoff", type=float, default=5.0, help="pause initiale entre tentatives (secondes)")
    ap.add_argument("--max-tech-streak", type=int, default=3,
                    help="arrêter après N erreurs techniques consécutives (quota épuisé) ; 0 = jamais")
    args = ap.parse_args()

    base = Config()
    golden = load_golden(args.golden)
    if args.check_gold:
        raise SystemExit(1 if check_gold(base, make_backend(base), golden) else 0)
    include_review = args.include_review or _review_index_exists()
    if not include_review:
        print("Questions d'avis ignorées : index BM25 absent (python -m scripts.build_reviews_index).")
    golden = select_questions(golden, args.split, include_review)
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
    df = run_benchmark(base, profiles, golden, sleep_s=args.sleep, retries=args.retries, backoff_s=args.backoff,
                       max_tech_streak=args.max_tech_streak)
    if df.empty:
        raise SystemExit(1)
    print(df.T.to_string(header=False) if len(df) == 1 else df.to_string(index=False))


if __name__ == "__main__":
    main()
