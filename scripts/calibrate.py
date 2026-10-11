"""Calibrate alarm / review / confidence_gate (and the ASR keyword floor) from ASR-mode pipeline traces.

    python scripts/calibrate.py [--set all|tune] [--write]

--set all (default since 11 Oct 05:00): every case call, "tuned on all case data; independent test = jury hidden set".
--set tune: dev + Testset_30 only (the T5 protocol, holdout kept unseen).
The ASR keyword floor (rules.yaml defaults.keyword_only_risk_asr) is a grid dimension too; --write saves only
config/thresholds.json and prints the floor to put into rules.yaml by hand (keeps its comments).

Re-decides every call (decide_call over the cached transcript, facts and audio analysis; no ASR, no LLM) for each
grid point. Objective: escalation F1 over the set (--set tune: equal-weight mean of dev and Testset_30, as in T2/T4),
ties -> strict-alarm precision, then the point closest to the current config. Default --objective esc_bacc
(escalation balanced accuracy): on all 62 calls escalation F1 is maximised by sending almost everything to review
(34 of 62 need escalation) and 3-class macro F1 by flagging almost nothing; balanced accuracy is 0.5 for both.
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
KW_FLOORS = [None, 0.3, 0.35, 0.4, 0.5]                          # None = keyword_only_risk (no ASR floor)


def tuning_ids(which: str = "all") -> list[str]:
    s = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"]
    return [c for name in (("dev", "test") if which == "tune" else ("dev", "test", "holdout")) for c in s[name]["call_ids"]]


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
    ap.add_argument("--set", choices=("all", "tune"), default="all")
    ap.add_argument("--objective", choices=("esc_bacc", "esc_f1", "macro_f1"), default="esc_bacc",
                    help="esc_bacc (default): escalation balanced accuracy (recall + specificity) / 2, where flag-all "
                         "and flag-none both score 0.5; macro_f1 (3-class) favours flagging almost nothing; esc_f1 rewards sending everything to review when most calls "
                         "need escalation (34 of 62: flag-all scores esc F1 0.71)")
    a = ap.parse_args(argv)
    ids = tuning_ids(a.set)
    inputs = load_inputs(ids)
    import yaml
    kw_doc = json.loads((dec.CONFIG_DIR / "keywords.json").read_text(encoding="utf-8"))
    rules_doc = yaml.safe_load((dec.CONFIG_DIR / "rules.yaml").read_text(encoding="utf-8"))
    th_doc = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    base = dec.load_config()
    cur_floor = rules_doc.get("defaults", {}).get("keyword_only_risk_asr")

    def with_floor(f):
        d = json.loads(json.dumps(rules_doc))
        d.setdefault("defaults", {})["keyword_only_risk_asr"] = f
        return dec.config_from_dicts(kw_doc, d, th_doc)
    floors = {f: with_floor(f) for f in KW_FLOORS}
    cur = base.thresholds
    hits = {cid: kw.find_hits(t, base.keywords) for cid, t, _, _ in inputs}      # thresholds never change the hits
    rows = []
    for fl, al, rv, g in itertools.product(KW_FLOORS, ALARMS, REVIEWS, GATES):
        if rv >= al:
            continue
        cfg = dec.with_thresholds(floors[fl], alarm=al, review=rv, confidence_gate=g)
        m = evaluate.score_decisions(decisions_for(inputs, cfg, hits))
        esc = lambda k: (m.get(k) or {}).get("escalation", {}).get("f1") or 0.0
        e = m["all"]["escalation"]
        bacc = (e["tp"] / max(1, e["tp"] + e["fn"]) + e["tn"] / max(1, e["tn"] + e["fp"])) / 2
        if a.objective == "esc_bacc":
            obj = bacc
        elif a.objective == "macro_f1":
            obj = m["all"]["three_class"]["macro_f1"] or 0.0
        else:
            obj = (esc("dev") + esc("test")) / 2 if a.set == "tune" else esc("all")
        rows.append({"keyword_only_risk_asr": fl, "alarm": al, "review": rv, "confidence_gate": g,
                     "esc_f1_mean": round(obj, 4), "objective": a.objective, "esc_bacc": round(bacc, 4),
                     "esc_p": e["precision"], "esc_r": e["recall"], "esc_f1": m["all"]["escalation"]["f1"],
                     "esc_f1_dev": esc("dev"), "esc_f1_test": esc("test"), "esc_f1_holdout": esc("holdout"),
                     "alarm_p": m["all"]["strict_alarm"]["precision"], "alarm_r": m["all"]["strict_alarm"]["recall"],
                     "macro_f1": m["all"]["three_class"]["macro_f1"], "pred_counts": m["all"]["pred_counts"],
                     "false_alarms": m["all"]["three_class"]["confusion"]["no_alert"]["alarm"],
                     "dist": round(abs(al - cur.alarm) + abs(rv - cur.review) + abs(g - cur.confidence_gate)
                                   + (0 if fl == cur_floor else 0.05), 3)})
    rows.sort(key=lambda r: (-r["esc_f1_mean"], -(r["esc_f1"] or 0.0), -(r["alarm_p"] or 0.0), r["dist"]))
    trivial = {k: evaluate.score_decisions({c: k for c in ids})["all"] for k in ("review", "no_alert")}
    print("trivial: flag-all-review esc F1 %.3f macro %.3f | all-no_alert macro %.3f" % (
        trivial["review"]["escalation"]["f1"], trivial["review"]["three_class"]["macro_f1"],
        trivial["no_alert"]["three_class"]["macro_f1"]))
    cur_row = next((r for r in rows if (r["alarm"], r["review"], r["confidence_gate"], r["keyword_only_risk_asr"])
                    == (cur.alarm, cur.review, cur.confidence_gate, cur_floor)), None)
    per_floor = {str(f): max((r for r in rows if r["keyword_only_risk_asr"] == f),
                             key=lambda r: (r["esc_f1_mean"], r["alarm_p"] or 0.0)) for f in KW_FLOORS}
    run_id = "calibration_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json_atomic(REPO_ROOT / "artifacts" / "metrics" / f"{run_id}.json",
                      {"run_id": run_id, "set": a.set, "calls": ids,
                       "objective": "esc F1 over the set (tune: mean of dev and test); ties alarm P",
                       "current": cur_row, "best": rows[0], "best_per_keyword_floor": per_floor, "top": rows[:20]})
    print("current:", cur_row)
    for f, r in per_floor.items():
        print(f"best with keyword floor {f}: objective {r['esc_f1_mean']:.3f} macro {r['macro_f1']:.3f} esc F1 {r['esc_f1']:.3f} alarm P {r['alarm_p']} R {r['alarm_r']:.2f} "
              f"FA {r['false_alarms']} pred {r['pred_counts']} at alarm {r['alarm']} review {r['review']} gate {r['confidence_gate']}")
    for r in rows[:8]:
        print(r)
    if a.write:
        doc = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
        best = rows[0]
        doc.update(alarm=best["alarm"], review=best["review"], confidence_gate=best["confidence_gate"])
        doc["_calibrated"] = (f"{run_id}: grid over {'all 62 case calls' if a.set == 'all' else 'dev + Testset_30'} "
                              f"ASR-mode traces, objective {a.objective} = {best['esc_f1_mean']}; keyword floor "
                              f"{best['keyword_only_risk_asr']} (rules.yaml)")
        write_json_atomic(THRESHOLDS_FILE, doc)
        print(f"wrote {THRESHOLDS_FILE.relative_to(REPO_ROOT)}")
    print(f"written artifacts/metrics/{run_id}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
