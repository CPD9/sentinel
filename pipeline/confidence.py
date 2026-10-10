"""Step 7: confidence gate. Combines five components, each in [0, 1] with 1 = "no concern".

# ---------------------------------------------------------------------------------------------------------
# FORMULA (weights, parameters and the formula name live in config/thresholds.json -> "confidence")
#
#   asr                  mean over the evidence segments (segments cited by valid facts; all segments if none) of
#                          clip((avg_logprob - floor) / (ceiling - floor), 0, 1) * (1 - no_speech_prob)
#                        1.0 for segments without ASR numbers (reference transcripts).
#   threshold_proximity  clip(min(|risk - alarm|, |risk - review|) / proximity_margin, 0, 1)
#                        risk is the call's max rule risk: a risk sitting on a threshold is a fragile decision.
#   conflicts            clip(1 - n_conflicts * conflict_penalty, 0, 1)
#   missing_evidence     clip(1 - n_dropped_facts * missing_evidence_penalty, 0, 1)   (facts the validator dropped)
#   audio_quality        AnalysisArtifact.audio_quality.call_score when present, else `audio_quality_neutral`
#                        (default 1.0: a missing analysis artifact never lowers confidence).
#
#   formula "weighted_mean":       value = sum(w_i * c_i) / sum(w_i)
#   formula "weighted_geometric":  value = prod(max(c_i, 1e-6) ** (w_i / sum(w))); punishes one bad component harder.
#
# gate_scope (used by decide.py): "any" = value < confidence_gate always sends the call to review;
#                                 "risky_only" = only if max risk >= review threshold or any keyword hit exists.
# All numbers are judgement placeholders, not calibrated. The reliability diagram in the Quality lab is the check.
# ---------------------------------------------------------------------------------------------------------
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pipeline.keywords import ConfigError
from pipeline.schemas import CONFIDENCE_COMPONENTS, AnalysisArtifact, ConfidenceBreakdown, Fact, Transcript

FORMULAS = ("weighted_mean", "weighted_geometric")
GATE_SCOPES = ("any", "risky_only")
_PARAMS = ("asr_logprob_floor", "asr_logprob_ceiling", "proximity_margin", "conflict_penalty",
           "missing_evidence_penalty", "audio_quality_neutral")


@dataclass
class ConfidenceParams:
    formula: str
    gate_scope: str
    weights: dict[str, float]
    params: dict[str, float]


def parse_confidence(d: dict) -> ConfidenceParams:
    errs = []
    formula, scope = d.get("formula", "weighted_mean"), d.get("gate_scope", "risky_only")
    if formula not in FORMULAS:
        errs.append(f"confidence.formula {formula!r} not in {FORMULAS}")
    if scope not in GATE_SCOPES:
        errs.append(f"confidence.gate_scope {scope!r} not in {GATE_SCOPES}")
    w = d.get("weights") or {}
    errs += [f"confidence.weights.{k}: unknown component" for k in w if k not in CONFIDENCE_COMPONENTS]
    errs += [f"confidence.weights.{k} must be a number >= 0" for k in CONFIDENCE_COMPONENTS
             if not isinstance(w.get(k), (int, float)) or isinstance(w.get(k), bool) or w.get(k) < 0]
    if not errs and sum(w.values()) <= 0:
        errs.append("confidence.weights must not all be 0")
    p = d.get("params") or {}
    errs += [f"confidence.params.{k} must be a number" for k in _PARAMS if not isinstance(p.get(k), (int, float)) or isinstance(p.get(k), bool)]
    if not errs and not p["asr_logprob_floor"] < p["asr_logprob_ceiling"]:
        errs.append("confidence.params: need asr_logprob_floor < asr_logprob_ceiling")
    if not errs and p["proximity_margin"] <= 0:
        errs.append("confidence.params.proximity_margin must be > 0")
    if errs:
        raise ConfigError(errs)
    return ConfidenceParams(formula, scope, {k: float(w[k]) for k in CONFIDENCE_COMPONENTS}, {k: float(p[k]) for k in _PARAMS})


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute(transcript: Transcript, facts: list[Fact], analysis: AnalysisArtifact | None, risk: float,
            n_conflicts: int, alarm: float, review: float, gate: float, cp: ConfidenceParams) -> ConfidenceBreakdown:
    p = cp.params
    cited = {s for f in facts if f.valid for s in f.segment_ids}
    segs = [s for s in transcript.segments if s.id in cited] or list(transcript.segments)
    vals = []
    for s in segs:
        if s.avg_logprob is None:
            vals.append(1.0)
        else:
            lp = _clip((s.avg_logprob - p["asr_logprob_floor"]) / (p["asr_logprob_ceiling"] - p["asr_logprob_floor"]))
            vals.append(lp * (1.0 - (s.no_speech_prob or 0.0)))
    aq = analysis.audio_quality if analysis is not None else None
    comps = {
        "asr": sum(vals) / len(vals) if vals else 1.0,
        "threshold_proximity": _clip(min(abs(risk - alarm), abs(risk - review)) / p["proximity_margin"]),
        "conflicts": _clip(1.0 - n_conflicts * p["conflict_penalty"]),
        "missing_evidence": _clip(1.0 - sum(1 for f in facts if not f.valid) * p["missing_evidence_penalty"]),
        "audio_quality": _clip(aq.call_score) if aq is not None else _clip(p["audio_quality_neutral"]),
    }
    w, tot = cp.weights, sum(cp.weights.values())
    if cp.formula == "weighted_geometric":
        value = math.exp(sum(w[k] / tot * math.log(max(c, 1e-6)) for k, c in comps.items()))
    else:
        value = sum(w[k] * c for k, c in comps.items()) / tot
    return ConfidenceBreakdown(round(_clip(value), 4), gate, {k: round(c, 4) for k, c in comps.items()})
