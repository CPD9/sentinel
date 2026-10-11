"""Calibrate alarm / review / confidence_gate on the tuning set (dev + Testset_30) from ASR-mode pipeline traces.

    python scripts/calibrate.py [--write]

Re-decides every tuning call (decide_call over the cached transcript, facts and audio analysis; no ASR, no LLM) for
each threshold triple on a grid. Objective: equal-weight mean of dev and Testset_30 escalation F1 (as in T2/T4),
ties -> strict-alarm precision, then the triple closest to the current config. Holdout calls are refused.
Labels are read only inside pipeline.evaluate (score_decisions). --write saves config/thresholds.json.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import decide as dec  # noqa: E402
from pipeline import evaluate, stages  # noqa: E402
from pipeline import keywords as kw  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.schemas import DecisionTrace, Transcript  # noqa: E402

SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
TRACES = REPO_ROOT / "artifacts" / "traces"
TRANSCRIPTS = REPO_ROOT / "artifacts" / "transcripts"
ANALYSIS = REPO_ROOT / "artifacts" / "analysis"
THRESHOLDS_FILE = REPO_ROOT / "config" / "thresholds.json"
ALARMS = [round(0.5 + 0.05 * i, 2) for i in range(9)]          # 0.50 .. 0.90
REVIEWS = [round(0.2 + 0.05 * i, 2) for i in range(10)]         # 0.20 .. 0.65
GATES = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7]


def tuning_ids() -> list[str]:
    s = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"]
    return s["dev"]["call_ids"] + s["test"]["call_ids"]


def load_inputs(ids: list[str]):
    out = []
    for cid in ids:
        t = Transcript.from_dict(json.loads((TRANSCRIPTS / f"{cid}.json").read_text(encoding="utf-8")))
        tr = json.loads((TRACES / f"{cid}.json").read_text(encoding="utf-8"))
        failed = tr["decision_path"] == "stage_error"
        facts = None if failed else DecisionTrace.from_dict(tr).facts
        out.append((cid, t, facts, stages.load_analysis(cid, ANALYSIS)))
    return out


def decisions_for(inputs, config, hits: dict) -> dict[str, str]:
    out = {}
    for cid, t, facts, analysis in inputs:
        tr = dec.decide_call(t, facts, analysis, config, hits=hits[cid], validate=False)
        out[cid] = tr.decision
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="save the best triple to config/thresholds.json")
    a = ap.parse_args(argv)
    ids = tuning_ids()
    inputs = load_inputs(ids)
    base = dec.load_config()
    cur = base.thresholds
    hits = {cid: kw.find_hits(t, base.keywords) for cid, t, _, _ in inputs}      # thresholds never change the hits
    rows = []
    for al, rv, g in itertools.product(ALARMS, REVIEWS, GATES):
        if rv >= al:
            continue
        cfg = dec.with_thresholds(base, alarm=al, review=rv, confidence_gate=g)
        m = evaluate.score_decisions(decisions_for(inputs, cfg, hits))
        esc = lambda k: m[k]["escalation"]["f1"] or 0.0
        rows.append({"alarm": al, "review": rv, "confidence_gate": g,
                     "esc_f1_mean": round((esc("dev") + esc("test")) / 2, 4), "esc_f1": m["all"]["escalation"]["f1"],
                     "esc_f1_dev": esc("dev"), "esc_f1_test": esc("test"),
                     "alarm_p": m["all"]["strict_alarm"]["precision"], "alarm_r": m["all"]["strict_alarm"]["recall"],
                     "macro_f1": m["all"]["three_class"]["macro_f1"], "pred_counts": m["all"]["pred_counts"],
                     "false_alarms": m["all"]["three_class"]["confusion"]["no_alert"]["alarm"],
                     "dist": round(abs(al - cur.alarm) + abs(rv - cur.review) + abs(g - cur.confidence_gate), 3)})
    rows.sort(key=lambda r: (-r["esc_f1_mean"], -(r["alarm_p"] or 0.0), r["dist"]))
    cur_row = next((r for r in rows if (r["alarm"], r["review"], r["confidence_gate"])
                    == (cur.alarm, cur.review, cur.confidence_gate)), None)
    run_id = "calibration_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json_atomic(REPO_ROOT / "artifacts" / "metrics" / f"{run_id}.json",
                      {"run_id": run_id, "calls": ids, "objective": "mean(dev esc F1, test esc F1); ties alarm P",
                       "current": cur_row, "best": rows[0], "top": rows[:20]})
    print("current:", cur_row)
    for r in rows[:8]:
        print(r)
    if a.write:
        doc = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
        best = rows[0]
        doc.update(alarm=best["alarm"], review=best["review"], confidence_gate=best["confidence_gate"])
        doc["_calibrated"] = (f"{run_id}: grid over dev + Testset_30 ASR-mode traces, objective mean(dev, test) "
                              f"escalation F1 = {best['esc_f1_mean']}; holdout not used")
        write_json_atomic(THRESHOLDS_FILE, doc)
        print(f"wrote {THRESHOLDS_FILE.relative_to(REPO_ROOT)}")
    print(f"written artifacts/metrics/{run_id}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
