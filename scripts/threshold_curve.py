"""Threshold curve for the demo: false alarms, missed cases and review load over the adjustable thresholds.

    python scripts/threshold_curve.py --out-dir ~/Developer/sentinel-runs/s4t_<HHMM>_final

Re-decides all calls through pipeline.simulate (cached judge, facts and keyword results; no ASR, no LLM) for
  - the review threshold 0.00 .. 1.00 (alarm fixed at its configured value, kept above review),
  - the alarm threshold 0.05 .. 1.00 (review fixed),
  - keyword review off / on (min_segments 1 .. 4),
and counts against the gold labels (through pipeline.evaluate): false alarms = gold no_alert decided alarm; missed
cases = gold alarm/review decided no_alert; review load = share of calls a person has to look at (alarm + review).
Writes artifacts/metrics/threshold_curve.json. In-sample on all case calls (the thresholds were not tuned on them).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import evaluate  # noqa: E402
from pipeline import simulate as sim  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402


def point(s: sim.Simulator, patch: dict) -> dict:
    d = s.decisions(patch)
    m = evaluate.score_decisions(d)["all"]
    cm = m["three_class"]["confusion"]
    e = m["escalation"]
    return {"false_alarms": cm["no_alert"]["alarm"],
            "missed": cm["alarm"]["no_alert"] + cm["review"]["no_alert"],
            "review_load": round(sum(v != "no_alert" for v in d.values()) / len(d), 4),
            "alarms": sum(v == "alarm" for v in d.values()), "reviews": sum(v == "review" for v in d.values()),
            "esc_p": e["precision"], "esc_r": e["recall"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, required=True, help="run folder with results/ and judge/")
    ap.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts", help="traces/ transcripts/ analysis/")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    run_ids = {p.stem for p in (a.out_dir / "results").glob("*.json")}
    inputs = [i for i in sim.load_inputs(a.artifacts, a.out_dir) if i.call_id in run_ids]   # this run's calls only
    s = sim.Simulator(inputs)
    th = s.raw.thresholds
    t1 = time.perf_counter()
    s.decisions({"thresholds": {"review": 0.3}})
    t_one = time.perf_counter() - t1
    grid = [round(0.05 * i, 2) for i in range(20)]          # 0.00 .. 0.95 (an alarm threshold of 1.0 is not a setting)
    review = [{"review": r, **point(s, {"thresholds": {"review": r, "alarm": min(0.95, max(th["alarm"], round(r + 0.05, 2)))}})}
              for r in grid if r < 0.95]
    alarm = [{"alarm": al, **point(s, {"thresholds": {"alarm": al, "review": min(th["review"], round(al - 0.05, 2))}})}
             for al in grid if al > 0]
    kwr = [{"keyword_review": False, **point(s, {})}] + [
        {"keyword_review": True, "min_segments": n,
         **point(s, {"thresholds": {"keyword_review": {"enabled": True, "min_segments": n}}})} for n in (1, 2, 3, 4)]
    out = {"calls": len(inputs), "current": {"alarm": th["alarm"], "review": th["review"],
                                             "keyword_review": th.get("keyword_review")},
           "current_point": point(s, {}), "review_threshold": review, "alarm_threshold": alarm, "keyword_review": kwr,
           "seconds_one_simulation": round(t_one, 3), "seconds_total": round(time.perf_counter() - t0, 2),
           "note": "in-sample on all case calls; false alarms = gold no_alert -> alarm; missed = gold alarm/review -> "
                   "no_alert; review load = (alarm + review) / calls"}
    write_json_atomic(REPO_ROOT / "artifacts" / "metrics" / "threshold_curve.json", out)
    print(f"{len(inputs)} calls; one what-if simulation {t_one * 1000:.0f} ms")
    print("review threshold: " + "  ".join(f"{p['review']:.2f}:FA{p['false_alarms']}/miss{p['missed']}/load{p['review_load']:.0%}"
                                           for p in review[::2]))
    print("keyword review:   " + "  ".join(f"{'off' if not p['keyword_review'] else 'min' + str(p['min_segments'])}:"
                                           f"FA{p['false_alarms']}/miss{p['missed']}/load{p['review_load']:.0%}" for p in kwr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
