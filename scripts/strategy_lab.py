"""T4 strategy lab: five detection strategies on the tuning set (dev + Testset_30), reference transcripts.

    python scripts/strategy_lab.py \\
        --facts artifacts/traces_extract/extract_builder_pod_apertus-8b_reference_tune_v2 \\
        --direct artifacts/predictions/baseline_direct_<tag>_dev.json artifacts/predictions/baseline_direct_<tag>_test.json

Strategies (decisions only from transcripts, cached LLM facts and config; labels are read only by pipeline.evaluate):
  S1 keywords_only  keyword hits alone: a family with hits in >= ALARM_SEGMENTS distinct segments -> alarm,
                    any hit -> review, none -> no_alert (untuned placeholder numbers)
  S2 context_only   LLM facts -> rules -> confidence -> decision with NO keyword hits
  S3 hybrid         the pipeline as shipped: LLM facts + keyword hits (decide_call)
  S4 direct_judge   one LLM prompt per call over the whole transcript (scripts/baseline_direct.py predictions)
  S8 ensemble       majority of S1, S3, S4; no majority (all three differ) -> review

S2/S3 re-decide the cached facts with the current config/, so they reflect today's rules and thresholds.
Writes artifacts/predictions/strategy_<name>_tune.json per strategy, artifacts/bench/<run_id>/{summary,per_call}.json
and config/strategy_defaults.json (top 3 by the T2 ranking rule).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import decide as dec  # noqa: E402
from pipeline import evaluate, stages  # noqa: E402
from pipeline import keywords as kw  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.schemas import (CRITERION_BY_FAMILY, DECISIONS, CallResult, Fact, Finding, RunResult,  # noqa: E402
                              Versions)

SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
PRED_DIR = REPO_ROOT / "artifacts" / "predictions"
BENCH_DIR = REPO_ROOT / "artifacts" / "bench"
DEFAULTS_FILE = REPO_ROOT / "config" / "strategy_defaults.json"
TUNE_SPLITS = ("dev", "test")            # never holdout
ALARM_SEGMENTS = 3                       # S1: distinct segments with hits of one family for an alarm
STRATEGIES = {
    "S1": ("keywords_only", "Keyword families alone, no LLM"),
    "S2": ("context_only", "LLM facts and rules, no keyword hits"),
    "S3": ("hybrid", "LLM facts + keyword hits through the rules (the shipped pipeline)"),
    "S4": ("direct_judge", "One LLM prompt judges the whole call"),
    "S8": ("ensemble", "Majority of S1, S3, S4; disagreement becomes review"),
}
ENSEMBLE_OF = ("S1", "S3", "S4")


def tune_call_ids() -> list[str]:
    splits = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"]
    return [cid for s in TUNE_SPLITS for cid in splits[s]["call_ids"]]


# --------------------------------------------------------------------------- strategies (label-free)

def keywords_only(hits) -> tuple[str, float, str]:
    segs: dict[str, set] = {}
    for h in hits:
        segs.setdefault(h.family, set()).add(h.segment_id)
    if not segs:
        return "no_alert", 0.0, "no keyword hit"
    fam, s = max(segs.items(), key=lambda kv: (len(kv[1]), kv[0]))
    n = len(s)
    decision = "alarm" if n >= ALARM_SEGMENTS else "review"
    return decision, round(min(1.0, n / ALARM_SEGMENTS), 3), \
        f"{CRITERION_BY_FAMILY.get(fam, fam)}: family '{fam}' hit in {n} segment(s) (alarm at {ALARM_SEGMENTS})"


def ensemble(decisions: list[str]) -> str:
    top, n = Counter(decisions).most_common(1)[0]
    return top if n >= 2 else "review"


def load_facts(trace_dir: Path, cid: str) -> list[Fact] | None:
    p = trace_dir / f"{cid}.json"
    if not p.is_file():
        return None
    return [Fact(**f) for f in json.loads(p.read_text(encoding="utf-8"))["facts"]]


def run_strategies(call_ids: list[str], trace_dir: Path, direct: dict[str, CallResult]) -> dict[str, list[dict]]:
    config = dec.load_config()
    out = {k: [] for k in STRATEGIES}
    for cid in call_ids:
        t, errs = stages.run_reference(cid)
        if t is None:
            raise SystemExit(f"{cid}: no reference transcript ({errs})")
        hits = kw.find_hits(t, config.keywords)
        facts = load_facts(trace_dir, cid)
        row = {}
        d, risk, why = keywords_only(hits)
        row["S1"] = {"decision": d, "risk": risk, "reason": why}
        for key, h in (("S2", []), ("S3", hits)):
            if facts is None:
                row[key] = {"decision": "review", "risk": 0.0, "reason": "no cached facts: stage error", "error": True}
                continue
            tr = dec.decide_call(t, facts, None, config, hits=h)
            fired = [r for r in tr.rules if r.fired]
            row[key] = {"decision": tr.decision, "risk": tr.risk_score, "path": tr.decision_path,
                        "reason": "; ".join(r.reason for r in fired) or tr.decision_path,
                        "criteria": [r.criterion for r in fired]}
        dc = direct.get(cid)
        if dc is None:
            row["S4"] = {"decision": "review", "risk": 0.0, "reason": "no direct-judge prediction: stage error", "error": True}
        else:
            row["S4"] = {"decision": dc.decision, "risk": dc.risk_score,
                         "reason": "; ".join(f.reason for f in dc.findings) or dc.narrative,
                         "criteria": [f.criterion for f in dc.findings], "error": bool(dc.stage_errors)}
        votes = [row[k]["decision"] for k in ENSEMBLE_OF]
        row["S8"] = {"decision": ensemble(votes), "risk": max(row[k]["risk"] for k in ENSEMBLE_OF),
                     "reason": "votes " + ", ".join(f"{k}={row[k]['decision']}" for k in ENSEMBLE_OF)}
        for k in STRATEGIES:
            out[k].append({"call_id": cid, **row[k]})
    return out


def write_predictions(key: str, rows: list[dict], versions: Versions) -> Path:
    name = STRATEGIES[key][0]
    calls = [CallResult(r["call_id"], r["decision"], float(r["risk"]), None,
                        findings=[Finding(c, float(r["risk"]), r["reason"]) for c in r.get("criteria", [])[:1]],
                        narrative=r["reason"], versions=versions) for r in rows]
    rr = RunResult(run_id=f"strategy_{key}_{name}_reference_tune", mode="reference", system=f"strategy:{name}",
                   provider="builder_pod" if key != "S1" else "none", created_at=datetime.now(timezone.utc).isoformat(),
                   calls=calls, notes=[f"T4 strategy lab {key} {name}: {STRATEGIES[key][1]}",
                                       "tuning set dev + Testset_30, reference transcripts, untuned rules/thresholds"])
    p = PRED_DIR / f"{rr.run_id}.json"
    write_json_atomic(p, rr.to_dict())
    return p


# --------------------------------------------------------------------------- metrics (labels via pipeline.evaluate)

def _score(gold, pred) -> dict:
    b = evaluate.metric_block(gold, pred)
    return {"esc_f1": b["escalation"]["f1"], "alarm_p": b["strict_alarm"]["precision"],
            "alarm_r": b["strict_alarm"]["recall"], "macro_f1": b["three_class"]["macro_f1"]}


def bootstrap(per_call: dict[str, list[dict]], n: int = 2000, seed: int = 20261011) -> dict:
    """Paired percentile bootstrap over calls: CI per strategy and per metric, plus P(A > B) on escalation F1."""
    keys = list(per_call)
    m = len(per_call[keys[0]])
    rng = random.Random(seed)
    samples = {k: {x: [] for x in ("esc_f1", "alarm_p", "alarm_r", "macro_f1")} for k in keys}
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        for k in keys:
            s = _score([per_call[k][i]["gold"] for i in idx], [per_call[k][i]["pred"] for i in idx])
            for x, v in s.items():
                samples[k][x].append(0.0 if v is None else v)
    ci = {k: {x: [round(sorted(v)[int(0.025 * n)], 3), round(sorted(v)[int(0.975 * n) - 1], 3)]
              for x, v in samples[k].items()} for k in keys}
    wins = {a: {b: round(sum(x > y for x, y in zip(samples[a]["esc_f1"], samples[b]["esc_f1"])) / n, 3)
                for b in keys if b != a} for a in keys}
    return {"n_resamples": n, "ci95": ci, "p_esc_f1_greater": wins}


def agreement(rows: dict[str, list[dict]]) -> dict:
    """Pairwise agreement rate and Cohen's kappa on the 3-class decisions (label-free)."""
    keys = list(rows)
    out = {}
    for a in keys:
        out[a] = {}
        for b in keys:
            da, db = [r["decision"] for r in rows[a]], [r["decision"] for r in rows[b]]
            po = sum(x == y for x, y in zip(da, db)) / len(da)
            ca, cb = Counter(da), Counter(db)
            pe = sum(ca[c] * cb[c] for c in DECISIONS) / len(da) ** 2
            out[a][b] = {"agree": round(po, 3), "kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0}
    return out


def r3(x):
    return None if x is None else round(x, 3)


def rank_key(s: dict):
    return (s["esc_f1_mean"] or 0.0, s["alarm_p"] or 0.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", type=Path, required=True, help="traces_extract run dir with the cached facts (S2, S3)")
    ap.add_argument("--direct", type=Path, nargs="+", required=True, help="baseline_direct predictions (S4)")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    call_ids = tune_call_ids()
    direct = {c.call_id: c for p in args.direct
              for c in RunResult.from_dict(json.loads(p.read_text(encoding="utf-8"))).calls}
    rows = run_strategies(call_ids, args.facts, direct)
    versions = Versions(llm="apertus-8b", prompt="extract-v2 / baseline-direct", provider="builder_pod", self_hosted=True)

    summary, scored = {}, {}
    for key, (name, desc) in STRATEGIES.items():
        pred = write_predictions(key, rows[key], versions)
        m_all, m_dev, m_test = (evaluate.evaluate(pred, s) for s in (None, "dev", "test"))
        o = m_all["overall"]
        esc = lambda m: m["overall"]["escalation"]["f1"]
        scored[key] = m_all["per_call"]
        summary[key] = {"strategy": name, "description": desc, "pred_file": str(pred.relative_to(REPO_ROOT)), "n": o["n"],
                        "esc_f1": o["escalation"]["f1"], "esc_f1_dev": esc(m_dev), "esc_f1_test": esc(m_test),
                        "esc_f1_mean": round((esc(m_dev) + esc(m_test)) / 2, 3)
                        if None not in (esc(m_dev), esc(m_test)) else None,
                        "esc_p": o["escalation"]["precision"], "esc_r": o["escalation"]["recall"],
                        "alarm_p": o["strict_alarm"]["precision"], "alarm_r": o["strict_alarm"]["recall"],
                        "macro_f1": o["three_class"]["macro_f1"], "confusion": o["three_class"]["confusion"],
                        "false_alarms_on_no_alert": o["three_class"]["confusion"]["no_alert"]["alarm"],
                        "stage_errors": sum(bool(r.get("error")) for r in rows[key]),
                        "per_stufe_esc_f1": {g: b["escalation"]["f1"] for g, b in m_all["breakdown"]["stufe"].items()}}
    boot = bootstrap(scored)
    for key in summary:
        summary[key]["ci95"] = boot["ci95"][key]
    ranked = sorted(summary, key=lambda k: rank_key(summary[k]), reverse=True)
    separable = [[a, b, boot["p_esc_f1_greater"][a][b]] for i, a in enumerate(ranked) for b in ranked[i + 1:]
                 if boot["p_esc_f1_greater"][a][b] >= 0.95]
    run_id = args.run_id or "strategy_lab_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
           "tuning_set": "dev + Testset_30 (reference transcripts)", "n_calls": len(call_ids),
           "facts_from": str(args.facts), "direct_from": [str(p) for p in args.direct],
           "ranking": "equal-weight mean of dev and test escalation F1; ties -> strict-alarm precision",
           "ranked": ranked, "strategies": summary, "bootstrap": boot,
           "separable_pairs_p95": separable, "agreement": agreement(rows),
           "caveats": ["untuned rules and thresholds", "clean/noisy twins share a script in reference mode, so the "
                       "call-level bootstrap is optimistic", "S1 numbers are placeholders"]}
    write_json_atomic(BENCH_DIR / run_id / "summary.json", out)
    write_json_atomic(BENCH_DIR / run_id / "per_call.json",
                      {cid: {k: rows[k][i] for k in STRATEGIES} for i, cid in enumerate(call_ids)})
    write_json_atomic(DEFAULTS_FILE, {
        "_comment": f"Top 3 detection strategies on dev + Testset_30 (run {run_id}); written by scripts/strategy_lab.py",
        "ranking": out["ranking"], "default": ranked[0],
        "top3": [{"id": k, "strategy": summary[k]["strategy"], "description": summary[k]["description"],
                  "esc_f1": r3(summary[k]["esc_f1"]), "esc_f1_ci95": summary[k]["ci95"]["esc_f1"],
                  "alarm_p": r3(summary[k]["alarm_p"]), "alarm_r": r3(summary[k]["alarm_r"])} for k in ranked[:3]]})

    print("| id | strategy | esc F1 dev | esc F1 test30 | esc F1 all [95% CI] | alarm P | alarm R | macro F1 | "
          "false alarms on no_alert |")
    print("|---|---|---|---|---|---|---|---|---|")
    f = lambda x: "n/a" if x is None else f"{x:.2f}"
    for k in ranked:
        s = summary[k]
        lo, hi = s["ci95"]["esc_f1"]
        print(f"| {k} | {s['strategy']} | {f(s['esc_f1_dev'])} | {f(s['esc_f1_test'])} | {f(s['esc_f1'])} "
              f"[{lo:.2f}, {hi:.2f}] | {f(s['alarm_p'])} | {f(s['alarm_r'])} | {f(s['macro_f1'])} | "
              f"{s['false_alarms_on_no_alert']} |")
    print("\nseparable (P(A > B) >= 0.95 on esc F1):", separable or "none")
    print(f"written {BENCH_DIR / run_id}/summary.json and {DEFAULTS_FILE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
