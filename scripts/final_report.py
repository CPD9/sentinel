"""Final evaluation reports for the quality lab, from the frozen full run (run.py --split all --predictions).

    python scripts/final_report.py artifacts/predictions/pipeline_asr_final.json

Writes artifacts/quality/ (QualityReport schema, one split per report, as the API serves them).
--protocol all (default since T5b, 11 Oct): final_report.json over all 62 case calls, "tuned on all case data;
independent test = the jury's hidden set". --protocol holdout (T5): final_report.json = unseen holdout plus
final_report_tuned_dev.json / final_report_tuned_test.json.
and prints the three conventions with CIs per split.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import evaluate  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402

QUALITY_DIR = REPO_ROOT / "artifacts" / "quality"
ALL_REPORTS = (("final_report", "all", "TUNED ON ALL CASE DATA (dev + Testset_30 + holdout); independent test = the "
                "jury's hidden set. The pre-fix holdout result (escalation F1 0.00) is kept in "
                "final_report_prefix_holdout.json"),)
REPORTS = (("final_report", "holdout", "UNSEEN holdout: run once with the frozen config, never used for any choice"),
           ("final_report_tuned_dev", "dev", "TUNED ON: dev split (prompt, rules, thresholds were chosen here)"),
           ("final_report_tuned_test", "test", "TUNED ON: Testset_30 (cleared by Outcept for tuning)"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pred", type=Path)
    ap.add_argument("--resamples", type=int, default=1000)
    ap.add_argument("--protocol", choices=("all", "holdout"), default="all")
    ap.add_argument("--note", action="append", default=[], help="extra note in every report")
    a = ap.parse_args(argv)
    f = lambda m: "n/a " if m["value"] is None else f"{m['value']:.2f} [{m['ci_low']:.2f}, {m['ci_high']:.2f}]"
    for rid, split, note in (ALL_REPORTS if a.protocol == "all" else REPORTS):
        rep = evaluate.quality_report(a.pred, split, rid, n_resamples=a.resamples, notes=[note, *a.note])
        write_json_atomic(QUALITY_DIR / f"{rid}.json", rep)
        o = rep["overall"]
        print(f"{rid} ({split}, n={o['n']}): strict alarm P {f(o['strict_alarm']['precision'])} R "
              f"{f(o['strict_alarm']['recall'])} | escalation P {f(o['escalation']['precision'])} R "
              f"{f(o['escalation']['recall'])} F1 {f(o['escalation']['f1'])} | macro F1 {f(o['three_class']['macro_f1'])}")
    print(f"written {QUALITY_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
