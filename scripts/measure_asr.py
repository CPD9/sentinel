"""One row per ASR-path variant, on all 62 case calls: facts per call, escalation P/R/F1 with a CI, false alarms.

    python scripts/measure_asr.py <label> <predictions.json> [--traces artifacts/traces] [--out artifacts/metrics/asr_steps.json]

Facts come from the DecisionTraces of that run (read them before the next run overwrites them). Metrics and the
bootstrap (dialogue groups, 1000 resamples) come from pipeline.evaluate.quality_report(split="all"). Appends a row
to --out so the steps of one session form one table. Labels stay inside pipeline.evaluate.
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
from pipeline.schemas import RunResult  # noqa: E402


def row(label: str, pred: Path, traces: Path, rules_override: dict | None = None) -> dict:
    run = RunResult.from_dict(json.loads(pred.read_text(encoding="utf-8")))
    facts = valid = 0
    for c in run.calls:
        p = traces / f"{c.call_id}.json"
        if p.is_file():
            t = json.loads(p.read_text(encoding="utf-8"))
            facts += len(t["facts"])
            valid += sum(f["valid"] for f in t["facts"])
    rep = evaluate.quality_report(pred, "all", f"measure_{label}")
    o = rep["overall"]
    e = o["escalation"]
    v = lambda m: m["value"]
    return {"step": label, "run_id": run.run_id, "n": o["n"], "facts_per_call": round(facts / len(run.calls), 2),
            "valid_facts_per_call": round(valid / len(run.calls), 2),
            "esc_p": v(e["precision"]), "esc_r": v(e["recall"]), "esc_f1": v(e["f1"]),
            "esc_f1_ci95": [e["f1"]["ci_low"], e["f1"]["ci_high"]],
            "alarm_p": v(o["strict_alarm"]["precision"]), "alarm_r": v(o["strict_alarm"]["recall"]),
            "macro_f1": v(o["three_class"]["macro_f1"]),
            "false_alarms": o["three_class"]["confusion"]["no_alert"]["alarm"],
            "reviews_on_no_alert": o["three_class"]["confusion"]["no_alert"]["review"],
            "stage_errors": sum(bool(c.stage_errors) for c in run.calls)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label")
    ap.add_argument("pred", type=Path)
    ap.add_argument("--traces", type=Path, default=REPO_ROOT / "artifacts" / "traces")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "metrics" / "asr_steps.json")
    a = ap.parse_args(argv)
    r = row(a.label, a.pred, a.traces)
    doc = json.loads(a.out.read_text(encoding="utf-8")) if a.out.is_file() else {"rows": []}
    doc["rows"] = [x for x in doc["rows"] if x["step"] != a.label] + [r]
    write_json_atomic(a.out, doc)
    f = lambda x: "n/a" if x is None else f"{x:.2f}"
    print(f"{r['step']}: facts/call {r['facts_per_call']} (valid {r['valid_facts_per_call']}) | esc P {f(r['esc_p'])} "
          f"R {f(r['esc_r'])} F1 {f(r['esc_f1'])} [{f(r['esc_f1_ci95'][0])}, {f(r['esc_f1_ci95'][1])}] | alarm P "
          f"{f(r['alarm_p'])} R {f(r['alarm_r'])} | FA {r['false_alarms']} (+{r['reviews_on_no_alert']} review) | "
          f"stage errors {r['stage_errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
