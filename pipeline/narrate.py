"""Step 9: narrative, written only AFTER the decision is locked.

TEMPLATE NARRATIVE (no LLM yet): deterministic text built from the DecisionTrace and the findings.
The LLM version replaces `narrate()` later; the signature stays. It never changes the decision.
"""
from __future__ import annotations

from pipeline.schemas import DecisionTrace, Finding

TEMPLATE_TAG = "[template narrative, no LLM]"

_PATH_TEXT = {
    "stage_error": "a pipeline stage failed, so the result cannot be trusted as an all-clear",
    "missing_evidence": "a candidate finding lost its evidence in validation",
    "contradictory_evidence": "supporting and counter evidence cite the same passage",
    "low_confidence": "confidence is below the gate",
    "alarm": "a rule hit reached the alarm threshold with validated evidence",
    "review_band": "risk is in the review band",
    "no_alert": "no rule reached the review threshold",
}


def narrate(trace: DecisionTrace, findings: list[Finding]) -> tuple[str, str | None, str | None]:
    """(narrative, why_not_flagged, what_would_change). The last two are None for alarms."""
    th = trace.thresholds
    conf = "n/a" if trace.confidence is None else f"{trace.confidence:.2f}"
    top = max(findings, key=lambda f: f.risk, default=None)
    lines = [f"{TEMPLATE_TAG} Decision {trace.decision} ({_PATH_TEXT[trace.decision_path]}); "
             f"risk {trace.risk_score:.2f}, confidence {conf}."]
    if top is not None:
        lines.append(f"Top rule: {top.reason}")
    why = change = None
    if trace.decision != "alarm":
        why = (f"Not an alarm: {_PATH_TEXT[trace.decision_path]}. Highest risk {trace.risk_score:.2f} "
               f"vs alarm threshold {th.alarm:.2f}; confidence {conf} vs gate {th.confidence_gate:.2f}.")
        if trace.decision_path == "stage_error":
            change = "Fix the failed stage and re-run the call."
        elif trace.decision_path == "no_alert":
            change = (f"Risk would have to reach {th.review:.2f} (review) or {th.alarm:.2f} (alarm), "
                      "e.g. through a validated fact supporting a rule.")
        elif trace.decision_path == "low_confidence":
            change = f"Confidence would have to reach the gate {th.confidence_gate:.2f} (better audio or ASR)."
        else:
            change = f"A validated, uncontradicted fact with risk >= {th.alarm:.2f} would make this an alarm."
        lines.append(why)
    return " ".join(lines), why, change
