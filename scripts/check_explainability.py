"""Explainability check over a finished run: every call the UI shows must carry its reasoning, nothing empty.

    python scripts/check_explainability.py out [--traces artifacts/traces]

Per call (out/results/<id>.json + the DecisionTrace in --traces):
  result     narrative non-empty; versions.asr/llm/prompt/rules set; alarm/review -> >= 1 finding with evidence
             (segment ids, timestamps, text) and, in ASR mode, a snippet file that exists (a review out of doubt,
             e.g. missing evidence or low confidence, is explained by why_not_flagged instead)
  trace      every enabled rule in config has a RuleResult with a reason; confidence_breakdown with all components;
             every valid fact has segment ids, quote and gloss_de
  narrative  non-alarm calls have why_not_flagged and what_would_change (alarms explain themselves by evidence)
Exit 1 and a list of gaps when anything is missing. Stage-error calls are reported, not hidden.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import decide as dec  # noqa: E402
from pipeline.schemas import CONFIDENCE_COMPONENTS  # noqa: E402

ENABLED = [c for c, r in dec.load_config().rules.rules.items() if r.enabled]
NO_EVIDENCE_PATHS = ("missing_evidence", "low_confidence", "contradictory_evidence", "stage_error")   # review by doubt


def check_call(res: dict, trace: dict | None, out_dir: Path) -> list[str]:
    doubt = trace is not None and trace["decision_path"] in NO_EVIDENCE_PATHS and bool(trace.get("why_not_flagged"))
    gaps = []
    cid = res["call_id"]
    if not res.get("narrative", "").strip():
        gaps.append("result.narrative empty")
    for k in ("asr", "llm", "prompt", "rules"):
        if not (res.get("versions") or {}).get(k):
            gaps.append(f"result.versions.{k} missing")
    if res["decision"] in ("alarm", "review") and not res.get("stage_errors"):
        ev = [e for f in res["findings"] for e in f["evidence"]]
        if not ev and not doubt:          # a review out of doubt is explained by why_not_flagged instead
            gaps.append(f"{res['decision']} without evidence")
        for e in ev:
            if not e.get("segment_ids") or not e.get("text"):
                gaps.append("evidence without segment ids or text")
            if e.get("start_s") is None or e.get("end_s") is None:
                gaps.append("evidence without timestamps")
            sp = e.get("snippet_path")
            if not sp or not ((out_dir / sp).is_file() or (REPO_ROOT / sp).is_file() or Path(sp).is_file()):
                gaps.append(f"evidence snippet missing ({sp})")
    if trace is None:
        return gaps + ["trace missing"]
    if trace["decision"] != res["decision"]:
        gaps.append(f"trace decision {trace['decision']} != result {res['decision']}")
    rules = {r["criterion"]: r for r in trace.get("rules", [])}
    gaps += [f"rule {c} missing" for c in ENABLED if c not in rules]
    gaps += [f"rule {c} without reason" for c, r in rules.items() if not r.get("reason")]
    cb = trace.get("confidence_breakdown")
    if not cb:
        gaps.append("confidence_breakdown missing")
    else:
        gaps += [f"confidence component {k} missing" for k in CONFIDENCE_COMPONENTS if k not in cb.get("components", {})]
    for f in trace.get("facts", []):
        if f["valid"] and not (f.get("segment_ids") and f.get("quote") and f.get("gloss_de")):
            gaps.append(f"fact {f['fact_id']} lacks segment_ids/quote/gloss_de")
    if trace["decision"] != "alarm" and not (trace.get("why_not_flagged") and trace.get("what_would_change")):
        gaps.append("why_not_flagged / what_would_change missing")
    return [f"{cid}: {g}" for g in gaps]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--traces", type=Path, default=REPO_ROOT / "artifacts" / "traces")
    a = ap.parse_args(argv)
    files = sorted((a.out / "results").glob("*.json"))
    if not files:
        print(f"no results in {a.out / 'results'}", file=sys.stderr)
        return 1
    gaps, decisions, errored = [], Counter(), []
    for p in files:
        res = json.loads(p.read_text(encoding="utf-8"))
        tp = a.traces / p.name
        trace = json.loads(tp.read_text(encoding="utf-8")) if tp.is_file() else None
        decisions[res["decision"]] += 1
        if res.get("stage_errors"):
            errored.append(res["call_id"])
        gaps += check_call(res, trace, a.out)
    print(f"{len(files)} calls {dict(decisions)}; stage-error calls: {errored or 'none'}")
    kinds = Counter(g.split(": ", 1)[1].split(" (")[0] for g in gaps)
    for k, n in kinds.most_common():
        print(f"  {n:3d} x {k}")
    print("OK: every call is fully explained" if not gaps else f"{len(gaps)} gaps")
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
