"""3-fold cross-validation of the threshold calibration across the existing splits (dev / Testset_30 / holdout).

    python scripts/crossval.py <label> --traces <traces dir> [--floor]  [--out artifacts/metrics/crossval.json]

Splits are dialogue-grouped already, so a fold never shares a dialogue with its training splits. For each held-out
split: tune alarm / review / confidence_gate (and, with --floor, the ASR keyword floor) on the other two splits with
the same grid and objective as scripts/calibrate.py (escalation F1, ties strict-alarm precision, then closeness to
the current config), then score the held-out split once. Pure re-decision over cached transcripts, facts and audio
analysis: no ASR, no LLM. Also reports the in-sample score after tuning on all 62 calls. Labels stay inside
pipeline.evaluate.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import calibrate as cal  # noqa: E402
import yaml  # noqa: E402

from pipeline import decide as dec  # noqa: E402
from pipeline import evaluate  # noqa: E402
from pipeline import keywords as kw  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402

SPLITS = ("dev", "test", "holdout")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label")
    ap.add_argument("--traces", type=Path, required=True)
    ap.add_argument("--floor", action="store_true", help="also tune the ASR keyword floor")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "metrics" / "crossval.json")
    a = ap.parse_args(argv)
    cal.TRACES = a.traces
    splits = json.loads(cal.SPLITS_FILE.read_text(encoding="utf-8"))["splits"]
    ids = {s: splits[s]["call_ids"] for s in SPLITS}
    inputs = {cid: x for x in cal.load_inputs([c for s in SPLITS for c in ids[s]]) for cid in [x[0]]}
    kw_doc = json.loads((dec.CONFIG_DIR / "keywords.json").read_text(encoding="utf-8"))
    rules_doc = yaml.safe_load((dec.CONFIG_DIR / "rules.yaml").read_text(encoding="utf-8"))
    th_doc = json.loads(cal.THRESHOLDS_FILE.read_text(encoding="utf-8"))
    base = dec.load_config()
    cur = base.thresholds
    hits = {cid: kw.find_hits(x[1], base.keywords) for cid, x in inputs.items()}

    def cfg_floor(f):
        d = json.loads(json.dumps(rules_doc))
        d.setdefault("defaults", {})["keyword_only_risk_asr"] = f
        return dec.config_from_dicts(kw_doc, d, th_doc)
    floors = {f: cfg_floor(f) for f in (cal.KW_FLOORS if a.floor else [None])}

    # decisions for every grid point and call, computed once
    grid = [(f, al, rv, g) for f, al, rv, g in itertools.product(floors, cal.ALARMS, cal.REVIEWS, cal.GATES) if rv < al]
    decided = {}
    for pt in grid:
        f, al, rv, g = pt
        c = dec.with_thresholds(floors[f], alarm=al, review=rv, confidence_gate=g)
        decided[pt] = {cid: dec.decide_call(x[1], x[2], x[3], c, hits=hits[cid], validate=False).decision
                       for cid, x in inputs.items()}

    def score(pt, calls):
        m = evaluate.score_decisions({c: decided[pt][c] for c in calls})["all"]
        return m["escalation"]["f1"] or 0.0, m["strict_alarm"]["precision"] or 0.0, m

    def tune(calls):
        def key(pt):
            f1, p, _ = score(pt, calls)
            dist = abs(pt[1] - cur.alarm) + abs(pt[2] - cur.review) + abs(pt[3] - cur.confidence_gate) + (pt[0] is not None) * 0.05
            return (-f1, -p, dist)
        return min(grid, key=key)

    folds = {}
    for held in SPLITS:
        train = [c for s in SPLITS if s != held for c in ids[s]]
        pt = tune(train)
        f1, p, m = score(pt, ids[held])
        folds[held] = {"tuned_on": [s for s in SPLITS if s != held], "point": dict(zip(("floor", "alarm", "review", "gate"), pt)),
                       "esc_f1": round(f1, 4), "esc_p": m["escalation"]["precision"], "esc_r": m["escalation"]["recall"],
                       "alarm_p": m["strict_alarm"]["precision"], "pred_counts": m["pred_counts"]}
    allc = [c for s in SPLITS for c in ids[s]]
    pt_all = tune(allc)
    f1_all, _, m_all = score(pt_all, allc)
    vals = [folds[s]["esc_f1"] for s in SPLITS]
    row = {"label": a.label, "folds": folds, "cv_mean": round(sum(vals) / 3, 4), "cv_min": min(vals), "cv_max": max(vals),
           "all62_in_sample": {"point": dict(zip(("floor", "alarm", "review", "gate"), pt_all)), "esc_f1": round(f1_all, 4),
                               "pred_counts": m_all["pred_counts"]},
           "flag_all_baseline": {s: round(evaluate.score_decisions({c: "review" for c in ids[s]})["all"]["escalation"]["f1"], 4)
                                 for s in SPLITS}}
    doc = json.loads(a.out.read_text(encoding="utf-8")) if a.out.is_file() else {"rows": []}
    doc["rows"] = [r for r in doc["rows"] if r["label"] != a.label] + [row]
    write_json_atomic(a.out, doc)
    print(f"{a.label}: dev {folds['dev']['esc_f1']:.2f} | test30 {folds['test']['esc_f1']:.2f} | holdout "
          f"{folds['holdout']['esc_f1']:.2f} | CV {row['cv_mean']:.2f} ({row['cv_min']:.2f}-{row['cv_max']:.2f}) | "
          f"all 62 in-sample {f1_all:.2f} | flag-all {row['flag_all_baseline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
