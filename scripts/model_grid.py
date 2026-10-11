"""T2 model x prompt grid: one table from run_extract predictions on the tuning set (dev + Testset_30).

    python scripts/model_grid.py artifacts/predictions/extract_builder_pod_apertus-8b_reference_tune.json ...

For each prediction file: escalation F1 (dev, test, equal-weight mean, combined + bootstrap CI), strict-alarm P/R,
macro-F1, false alarms on gold no_alert, tokens and latency per call (from the run_extract stats next to it).
Ranking: equal-weight mean of dev and test escalation F1 (v2 was tuned on dev, so test counts at least as much),
ties -> combined strict-alarm precision. Holdout is never read. Writes artifacts/metrics/model_grid.json.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import evaluate  # noqa: E402

METRICS_DIR = REPO_ROOT / "artifacts" / "metrics"


def bootstrap_esc_f1(per_call: list[dict], n: int = 2000, seed: int = 20261011) -> tuple[float, float]:
    """95 % percentile CI of escalation F1, resampling calls (clean/noisy twins are correlated: CI is optimistic)."""
    rng, vals = random.Random(seed), []
    for _ in range(n):
        s = [per_call[rng.randrange(len(per_call))] for _ in per_call]
        gold, pred = [c["gold"] for c in s], [c["pred"] for c in s]
        f1 = evaluate.binary(gold, pred, evaluate.FLAGGED)["f1"]
        vals.append(0.0 if f1 is None else f1)
    vals.sort()
    return round(vals[int(0.025 * n)], 3), round(vals[int(0.975 * n) - 1], 3)


def row(pred: Path) -> dict:
    m_all, m_dev, m_test = (evaluate.evaluate(pred, s) for s in (None, "dev", "test"))
    if "holdout" in m_all["splits_present"]:
        raise SystemExit(f"{pred} contains holdout predictions; the grid only reads the tuning set")
    o = m_all["overall"]
    esc = lambda m: m["overall"]["escalation"]["f1"]
    stats_file = METRICS_DIR / f"extract_{m_all['run_id']}.json"
    st = json.loads(stats_file.read_text(encoding="utf-8")) if stats_file.is_file() else {}
    s = st.get("summary", {})
    tok = [s.get("input_tokens_per_call_mean"), s.get("output_tokens_per_call_mean")]
    return {
        "run_id": m_all["run_id"], "provider": st.get("provider"), "model": st.get("model"),
        "prompt": st.get("prompt_version"), "self_hosted": st.get("self_hosted"),
        "n": o["n"], "n_dev": m_dev["overall"]["n"], "n_test": m_test["overall"]["n"],
        "calls_failed": s.get("calls_failed"),
        "esc_f1_dev": esc(m_dev), "esc_f1_test": esc(m_test),
        "esc_f1_mean": round((esc(m_dev) + esc(m_test)) / 2, 3) if None not in (esc(m_dev), esc(m_test)) else None,
        "esc_f1": o["escalation"]["f1"], "esc_f1_ci95": bootstrap_esc_f1(m_all["per_call"]),
        "esc_p": o["escalation"]["precision"], "esc_r": o["escalation"]["recall"],
        "alarm_p": o["strict_alarm"]["precision"], "alarm_r": o["strict_alarm"]["recall"],
        "macro_f1": o["three_class"]["macro_f1"],
        "false_alarms_on_no_alert": o["three_class"]["confusion"]["no_alert"]["alarm"],
        "reviews_on_no_alert": o["three_class"]["confusion"]["no_alert"]["review"],
        "pred_counts": o["pred_counts"], "gold_counts": o["gold_counts"],
        "tokens_in_per_call": tok[0], "tokens_out_per_call": tok[1],
        "latency_s_per_call": round(s["latency_ms_per_call_mean"] / 1000, 1) if s.get("latency_ms_per_call_mean") else None,
        "stage_error_calls": sum(bool(c["stage_errors"]) for c in m_all["per_call"]),
    }


def rank_key(r: dict):
    return (r["esc_f1_mean"] or 0.0, r["alarm_p"] or 0.0)


def fmt(x) -> str:
    return "n/a" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))


def table(rows: list[dict]) -> str:
    head = ("| model | prompt | esc F1 dev | esc F1 test30 | esc F1 mean | esc F1 all [95% CI] | alarm P | alarm R | "
            "macro F1 | false alarms on no_alert | failed calls | tok in/out per call | s per call |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for r in rows:
        lo, hi = r["esc_f1_ci95"]
        lines.append(f"| {r['model']} | {(r['prompt'] or '').split('+')[0]} | {fmt(r['esc_f1_dev'])} | "
                     f"{fmt(r['esc_f1_test'])} | {fmt(r['esc_f1_mean'])} | {fmt(r['esc_f1'])} [{lo:.2f}, {hi:.2f}] | "
                     f"{fmt(r['alarm_p'])} | {fmt(r['alarm_r'])} | {fmt(r['macro_f1'])} | "
                     f"{r['false_alarms_on_no_alert']} (+{r['reviews_on_no_alert']} review) | {fmt(r['calls_failed'])} | "
                     f"{fmt(r['tokens_in_per_call'])}/{fmt(r['tokens_out_per_call'])} | {fmt(r['latency_s_per_call'])} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pred", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=METRICS_DIR / "model_grid.json")
    args = ap.parse_args(argv)
    rows = sorted((row(p) for p in args.pred), key=rank_key, reverse=True)
    out = {"ranking": "equal-weight mean of dev and test escalation F1; ties -> strict-alarm precision",
           "winner": rows[0]["run_id"], "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(table(rows))
    print(f"\nwinner: {rows[0]['run_id']}  (written {args.out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
