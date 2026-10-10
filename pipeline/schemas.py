"""Output contract for one processed call. Source of truth for the API, web app and evaluation.

Stdlib dataclasses only (no pydantic in the pipeline venv). `CallResult.from_dict` validates and
raises `SchemaError` with every problem found; `validate_call_result` returns the list instead.

Per call:
  call_id, decision (alarm | review | no_alert), risk_score 0-1, confidence 0-1 (None = not computed),
  findings[] {criterion, risk, reason, evidence[], counter_evidence[]},
  evidence item {segment_ids, start_s, end_s, speaker, text, snippet_path},
  narrative, stage_errors[] {stage, message}, versions {asr, llm, prompt, rules}.

A predictions file (`artifacts/predictions/<run>.json`) wraps the per-call results in a `RunResult`.

Side artifacts for the API and web app (second half of this file, see docs/API.md, docs/PRODUCT.md):
  Transcript       artifacts/transcripts/<call_id>.json   Transcript tab, evidence checks
  DecisionTrace    artifacts/traces/<call_id>.json        Reasoning tab (facts -> rules -> confidence -> decision)
  AnalysisArtifact artifacts/analysis/<call_id>/analysis.json   Audio analysis tab; never feeds the decision
                   except `audio_quality`, which feeds the confidence gate
  QualityReport    artifacts/quality/<run>.json           Quality lab
  CallListItem     one row of GET /api/calls              Inbox
  ProcessingEvent  one SSE event                          Processing view
They are declared as dataclasses; `<Class>.validate(d)` checks the declared types (unknown keys are
errors) and then the semantic rules, `<Class>.from_dict(d)` raises `SchemaError`. CallResult and
RunResult above keep their hand-written validators.
"""
from __future__ import annotations

import functools
import types
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from typing import Any, Union, get_args, get_origin, get_type_hints

SCHEMA_VERSION = 1

DECISIONS = ("alarm", "review", "no_alert")
SPEAKERS = ("advisor", "customer", "unknown")
# Input modes: "reference" = organizer scripts as transcript (segment ids are turn ids, no timestamps),
# "asr" = our own transcription of the audio.
MODES = ("reference", "asr")

# One criterion per case test target (data/case/Stichwortliste.json "families").
CRITERIA = (
    "insider_trading",            # trade: own trade request because of own nonpublic information
    "credential_sharing",         # access: actual disclosure of a currently active access secret
    "third_party_disclosure",     # disclosure: adviser reveals protected third-party detail
    "documentation_concealment",  # documentation: request to hide a relevant fact from its recipient
    "control_evasion",            # splitting: connected partial movements to dodge an internal process
    "payment_card_data",          # numbers: classify a read-out number (no alarm from digits alone)
    "other",
)
CRITERION_BY_FAMILY = {
    "trade": "insider_trading",
    "access": "credential_sharing",
    "disclosure": "third_party_disclosure",
    "documentation": "documentation_concealment",
    "splitting": "control_evasion",
    "numbers": "payment_card_data",
}


class SchemaError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Evidence:
    segment_ids: list[str]
    speaker: str
    text: str
    start_s: float | None = None    # None only in reference mode (scripts have no timestamps)
    end_s: float | None = None
    snippet_path: str | None = None


@dataclass
class Finding:
    criterion: str
    risk: float
    reason: str
    evidence: list[Evidence] = field(default_factory=list)
    counter_evidence: list[Evidence] = field(default_factory=list)


@dataclass
class StageError:
    stage: str
    message: str


@dataclass
class Versions:
    asr: str | None = None
    llm: str | None = None
    prompt: str | None = None
    rules: str | None = None


@dataclass
class CallResult:
    call_id: str
    decision: str
    risk_score: float
    confidence: float | None
    findings: list[Finding] = field(default_factory=list)
    narrative: str = ""
    stage_errors: list[StageError] = field(default_factory=list)
    versions: Versions = field(default_factory=Versions)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CallResult":
        errors = validate_call_result(d)
        if errors:
            raise SchemaError(errors)
        return cls(
            call_id=d["call_id"],
            decision=d["decision"],
            risk_score=float(d["risk_score"]),
            confidence=None if d.get("confidence") is None else float(d["confidence"]),
            findings=[_finding(f) for f in d.get("findings", [])],
            narrative=d.get("narrative", ""),
            stage_errors=[StageError(**e) for e in d.get("stage_errors", [])],
            versions=Versions(**(d.get("versions") or {})),
        )


@dataclass
class RunResult:
    """A predictions file: one run of one system over a set of calls."""
    run_id: str
    mode: str
    system: str                      # e.g. "baseline_direct", "pipeline"
    provider: str                    # e.g. "llm:<model>" or "MOCK:keyword-v1"
    created_at: str
    calls: list[CallResult]
    schema_version: int = SCHEMA_VERSION
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        errors = []
        if d.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"schema_version {d.get('schema_version')!r} != {SCHEMA_VERSION}")
        if d.get("mode") not in MODES:
            errors.append(f"mode {d.get('mode')!r} not in {MODES}")
        for k in ("run_id", "system", "provider", "created_at"):
            if not isinstance(d.get(k), str) or not d.get(k):
                errors.append(f"{k} must be a non-empty string")
        calls = d.get("calls")
        if not isinstance(calls, list):
            errors.append("calls must be a list")
            calls = []
        seen = set()
        for i, c in enumerate(calls):
            errors += [f"calls[{i}]: {e}" for e in validate_call_result(c)]
            cid = c.get("call_id") if isinstance(c, dict) else None
            if cid in seen:
                errors.append(f"calls[{i}]: duplicate call_id {cid}")
            seen.add(cid)
        if errors:
            raise SchemaError(errors)
        return cls(run_id=d["run_id"], mode=d["mode"], system=d["system"], provider=d["provider"],
                   created_at=d["created_at"], calls=[CallResult.from_dict(c) for c in calls],
                   schema_version=d["schema_version"], notes=list(d.get("notes", [])))


def _evidence(e: dict) -> Evidence:
    return Evidence(segment_ids=list(e["segment_ids"]), speaker=e["speaker"], text=e["text"],
                    start_s=e.get("start_s"), end_s=e.get("end_s"), snippet_path=e.get("snippet_path"))


def _finding(f: dict) -> Finding:
    return Finding(criterion=f["criterion"], risk=float(f["risk"]), reason=f["reason"],
                   evidence=[_evidence(e) for e in f.get("evidence", [])],
                   counter_evidence=[_evidence(e) for e in f.get("counter_evidence", [])])


# --------------------------------------------------------------------------- validation

def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _unit(x: Any) -> bool:
    return _is_num(x) and 0.0 <= x <= 1.0


def _validate_evidence(e: Any, where: str) -> list[str]:
    if not isinstance(e, dict):
        return [f"{where}: must be an object"]
    errs = []
    ids = e.get("segment_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        errs.append(f"{where}.segment_ids must be a non-empty list of strings")
    if e.get("speaker") not in SPEAKERS:
        errs.append(f"{where}.speaker {e.get('speaker')!r} not in {SPEAKERS}")
    if not isinstance(e.get("text"), str):
        errs.append(f"{where}.text must be a string")
    s, t = e.get("start_s"), e.get("end_s")
    if (s is None) != (t is None):
        errs.append(f"{where}: start_s and end_s must both be set or both be null")
    elif s is not None:
        if not (_is_num(s) and _is_num(t)):
            errs.append(f"{where}: start_s/end_s must be numbers")
        elif not 0 <= s < t:
            errs.append(f"{where}: need 0 <= start_s < end_s, got {s}..{t}")
    sp = e.get("snippet_path")
    if sp is not None and not isinstance(sp, str):
        errs.append(f"{where}.snippet_path must be a string or null")
    return errs


def validate_call_result(d: Any) -> list[str]:
    if not isinstance(d, dict):
        return ["call result must be an object"]
    errs = []
    if not isinstance(d.get("call_id"), str) or not d.get("call_id"):
        errs.append("call_id must be a non-empty string")
    if d.get("decision") not in DECISIONS:
        errs.append(f"decision {d.get('decision')!r} not in {DECISIONS}")
    if not _unit(d.get("risk_score")):
        errs.append(f"risk_score {d.get('risk_score')!r} must be a number in [0, 1]")
    if d.get("confidence") is not None and not _unit(d.get("confidence")):
        errs.append(f"confidence {d.get('confidence')!r} must be null or a number in [0, 1]")
    if not isinstance(d.get("narrative", ""), str):
        errs.append("narrative must be a string")
    findings = d.get("findings", [])
    if not isinstance(findings, list):
        errs.append(f"findings must be a list, got {type(findings).__name__}")
        findings = []
    for i, f in enumerate(findings):
        w = f"findings[{i}]"
        if not isinstance(f, dict):
            errs.append(f"{w}: must be an object")
            continue
        if f.get("criterion") not in CRITERIA:
            errs.append(f"{w}.criterion {f.get('criterion')!r} not in {CRITERIA}")
        if not _unit(f.get("risk")):
            errs.append(f"{w}.risk must be a number in [0, 1]")
        if not isinstance(f.get("reason"), str):
            errs.append(f"{w}.reason must be a string")
        for k in ("evidence", "counter_evidence"):
            items = f.get(k, [])
            if not isinstance(items, list):
                errs.append(f"{w}.{k} must be a list")
                continue
            for j, e in enumerate(items):
                errs += _validate_evidence(e, f"{w}.{k}[{j}]")
    stage_errors = d.get("stage_errors", [])
    if not isinstance(stage_errors, list):
        errs.append(f"stage_errors must be a list, got {type(stage_errors).__name__}")
        stage_errors = []
    for i, e in enumerate(stage_errors):
        if not (isinstance(e, dict) and isinstance(e.get("stage"), str) and isinstance(e.get("message"), str)):
            errs.append(f"stage_errors[{i}] must be {{stage: str, message: str}}")
    # Hard rule: a failed stage is never silently no_alert.
    if stage_errors and d.get("decision") == "no_alert":
        errs.append("decision is no_alert although stage_errors is non-empty")
    v = d.get("versions", {})
    if not isinstance(v, dict) or set(v) - {"asr", "llm", "prompt", "rules"}:
        errs.append("versions must be an object with keys among asr, llm, prompt, rules")
    return errs


# =========================================================================== side artifacts
# Typed check + builder shared by the side artifacts. Supported annotations: str, int, float, bool,
# Any, X | None, list[X], dict[str, X] and dataclasses of those.

@functools.cache
def _hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _at(where: str, key: str) -> str:
    return f"{where}.{key}" if where else key


def _check_type(tp: Any, v: Any, where: str) -> list[str]:
    origin = get_origin(tp)
    if tp is Any:
        return []
    if origin in (Union, types.UnionType):
        args = get_args(tp)
        if v is None:
            return [] if type(None) in args else [f"{where} must not be null"]
        (inner,) = [a for a in args if a is not type(None)]
        return _check_type(inner, v, where)
    if v is None:
        return [f"{where} must not be null"]
    if origin is list:
        if not isinstance(v, list):
            return [f"{where} must be a list, got {type(v).__name__}"]
        (inner,) = get_args(tp)
        return [e for i, x in enumerate(v) for e in _check_type(inner, x, f"{where}[{i}]")]
    if origin is dict:
        if not isinstance(v, dict):
            return [f"{where} must be an object, got {type(v).__name__}"]
        inner = get_args(tp)[1]
        return [e for k, x in v.items() for e in _check_type(inner, x, _at(where, str(k)))]
    if is_dataclass(tp):
        if not isinstance(v, dict):
            return [f"{where or tp.__name__} must be an object, got {type(v).__name__}"]
        hints, names = _hints(tp), {f.name for f in fields(tp)}
        errs = [f"{_at(where, k)}: unknown key" for k in v if k not in names]
        for f in fields(tp):
            if f.name in v:
                errs += _check_type(hints[f.name], v[f.name], _at(where, f.name))
            elif f.default is MISSING and f.default_factory is MISSING:
                errs.append(f"{_at(where, f.name)} is required")
        return errs
    if tp is float:
        ok = _is_num(v)
    elif tp is int:
        ok = isinstance(v, int) and not isinstance(v, bool)
    elif tp in (str, bool):
        ok = isinstance(v, tp)
    else:
        raise TypeError(f"unsupported schema annotation {tp!r}")
    return [] if ok else [f"{where} must be {tp.__name__}, got {type(v).__name__}"]


def _build(tp: Any, v: Any) -> Any:
    origin = get_origin(tp)
    if v is None or tp is Any:
        return v
    if origin in (Union, types.UnionType):
        (inner,) = [a for a in get_args(tp) if a is not type(None)]
        return _build(inner, v)
    if origin is list:
        return [_build(get_args(tp)[0], x) for x in v]
    if origin is dict:
        return {k: _build(get_args(tp)[1], x) for k, x in v.items()}
    if is_dataclass(tp):
        hints = _hints(tp)
        return tp(**{f.name: _build(hints[f.name], v[f.name]) for f in fields(tp) if f.name in v})
    return float(v) if tp is float else v


class _Artifact:
    """Mixin: typed validation, then `_semantic(d)` (which may assume the types are right)."""

    @classmethod
    def validate(cls, d: Any) -> list[str]:
        errs = _check_type(cls, d, "")
        return errs or cls._semantic(d)

    @classmethod
    def _semantic(cls, d: dict) -> list[str]:
        return []

    @classmethod
    def from_dict(cls, d: dict):
        errs = cls.validate(d)
        if errs:
            raise SchemaError(errs)
        return _build(cls, d)

    def to_dict(self) -> dict:
        return asdict(self)


def _schema_version(d: dict) -> list[str]:
    v = d.get("schema_version", SCHEMA_VERSION)
    return [] if v == SCHEMA_VERSION else [f"schema_version {v!r} != {SCHEMA_VERSION}"]


def _enum(v: Any, allowed: tuple, where: str) -> list[str]:
    return [] if v in allowed else [f"{where} {v!r} not in {allowed}"]


def _in_unit(v: Any, where: str) -> list[str]:
    return [] if v is None or 0.0 <= v <= 1.0 else [f"{where} {v!r} must be in [0, 1]"]


TIME_TOLERANCE_S = 0.05


def _span(s: float, e: float, duration: float | None, where: str) -> list[str]:
    if not 0 <= s < e:
        return [f"{where}: need 0 <= start_s < end_s, got {s}..{e}"]
    if duration is not None and e > duration + TIME_TOLERANCE_S:
        return [f"{where}: end_s {e} beyond audio duration {duration}"]
    return []


def _times(ts: list[float], duration: float | None, where: str) -> list[str]:
    if any(b <= a for a, b in zip(ts, ts[1:])):
        return [f"{where} must be strictly increasing"]
    if ts and (ts[0] < 0 or (duration is not None and ts[-1] > duration + TIME_TOLERANCE_S)):
        return [f"{where} must lie inside [0, duration]"]
    return []


# --------------------------------------------------------------------------- shared pieces

@dataclass
class Axis:
    """Axis label and unit, shipped with the data so the UI never hardcodes them."""
    label: str
    unit: str     # e.g. "s", "Hz (mel scale)", "dB", "words/min", "score 0-1"


def _axes(axes: dict, required: tuple[str, ...], where: str, time_x: bool = True) -> list[str]:
    errs = [f"{where}.axes.{k} is required" for k in required if k not in axes]
    errs += [f"{where}.axes.{k}: unknown axis (use x, y, value)" for k in axes if k not in ("x", "y", "value")]
    errs += [f"{where}.axes.{k}.unit must be non-empty" for k, a in axes.items() if not a["unit"].strip()]
    if time_x and "x" in axes and axes["x"]["unit"] != "s":
        errs.append(f"{where}.axes.x.unit must be 's' (all lanes share one time axis)")
    return errs


# --------------------------------------------------------------------------- Transcript

@dataclass
class TranscriptSegment:
    id: str
    speaker: str
    text: str
    start_s: float | None = None          # None only in reference mode
    end_s: float | None = None
    avg_logprob: float | None = None      # ASR only
    no_speech_prob: float | None = None   # ASR only


@dataclass
class Transcript(_Artifact):
    call_id: str
    mode: str
    segments: list[TranscriptSegment]
    asr_model: str | None = None
    duration_s: float | None = None
    is_mock: bool = False
    notes: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def _semantic(cls, d: dict) -> list[str]:
        errs = _schema_version(d) + _enum(d["mode"], MODES, "mode")
        seen, dur = set(), d.get("duration_s")
        for i, s in enumerate(d["segments"]):
            w = f"segments[{i}]"
            if s["id"] in seen:
                errs.append(f"{w}: duplicate id {s['id']}")
            seen.add(s["id"])
            errs += _enum(s["speaker"], SPEAKERS, f"{w}.speaker")
            st, en = s.get("start_s"), s.get("end_s")
            if d["mode"] == "asr" and (st is None or en is None):
                errs.append(f"{w}: asr segments need start_s and end_s")
            elif (st is None) != (en is None):
                errs.append(f"{w}: start_s and end_s must both be set or both be null")
            elif st is not None:
                errs += _span(st, en, dur, w)
            errs += _in_unit(s.get("no_speech_prob"), f"{w}.no_speech_prob")
            if (s.get("avg_logprob") or 0) > 0:
                errs.append(f"{w}.avg_logprob must be <= 0")
        return errs


# --------------------------------------------------------------------------- DecisionTrace

FACT_ACTS = ("request", "disclose", "warn", "refuse", "hypothetical", "quote", "other")
INFO_TYPES = ("credentials", "nonpublic_info", "client_data", "other")
CONFIDENCE_COMPONENTS = ("asr", "threshold_proximity", "conflicts", "missing_evidence", "audio_quality")
# decide.py priority order -> the only decision each branch may produce.
DECISION_PATHS = {
    "stage_error": "review", "missing_evidence": "review", "contradictory_evidence": "review",
    "low_confidence": "review", "alarm": "alarm", "review_band": "review", "no_alert": "no_alert",
}


@dataclass
class Fact:
    fact_id: str
    speaker: str
    act: str
    info_type: str
    segment_ids: list[str]
    quote: str
    recipient_third_party: bool | None = None
    secrecy_cue: bool | None = None
    counter_evidence: str | None = None
    valid: bool = True                    # False = dropped by the evidence validator
    drop_reason: str | None = None


@dataclass
class KeywordHit:
    hit_id: str
    family: str                           # key of CRITERION_BY_FAMILY
    term: str                             # configured term or variant
    matched_text: str                     # what the transcript actually says
    segment_id: str
    score: float                          # fuzzy match score 0-1


@dataclass
class RuleResult:
    criterion: str
    risk: float
    fired: bool
    reason: str
    fact_ids: list[str] = field(default_factory=list)
    keyword_hit_ids: list[str] = field(default_factory=list)


@dataclass
class ConfidenceBreakdown:
    value: float
    gate: float
    components: dict[str, float]          # keys from CONFIDENCE_COMPONENTS, each 0-1 (1 = no concern)


@dataclass
class Thresholds:
    alarm: float
    review: float
    confidence_gate: float


@dataclass
class DecisionTrace(_Artifact):
    call_id: str
    decision: str
    decision_path: str
    risk_score: float
    confidence: float | None
    thresholds: Thresholds
    facts: list[Fact] = field(default_factory=list)
    keyword_hits: list[KeywordHit] = field(default_factory=list)
    rules: list[RuleResult] = field(default_factory=list)
    confidence_breakdown: ConfidenceBreakdown | None = None
    why_not_flagged: str | None = None
    what_would_change: str | None = None
    timings_s: dict[str, float] = field(default_factory=dict)
    versions: Versions = field(default_factory=Versions)
    is_mock: bool = False
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def _semantic(cls, d: dict) -> list[str]:
        errs = _schema_version(d) + _enum(d["decision"], DECISIONS, "decision")
        errs += _in_unit(d["risk_score"], "risk_score") + _in_unit(d["confidence"], "confidence")
        path = d["decision_path"]
        if path not in DECISION_PATHS:
            errs.append(f"decision_path {path!r} not in {tuple(DECISION_PATHS)}")
        elif DECISION_PATHS[path] != d["decision"]:
            errs.append(f"decision_path {path} cannot produce decision {d['decision']}")
        t = d["thresholds"]
        errs += [e for k in ("alarm", "review", "confidence_gate") for e in _in_unit(t[k], f"thresholds.{k}")]
        if not t["review"] < t["alarm"]:
            errs.append("thresholds: need review < alarm")
        if path == "alarm" and d["risk_score"] < t["alarm"]:
            errs.append("decision_path alarm but risk_score below the alarm threshold")
        if path == "review_band" and not t["review"] <= d["risk_score"] < t["alarm"]:
            errs.append("decision_path review_band but risk_score outside [review, alarm)")
        if path == "no_alert" and d["risk_score"] >= t["review"]:
            errs.append("decision_path no_alert but risk_score at or above the review threshold")
        if path in ("alarm", "no_alert") and (d["confidence"] is None or d["confidence"] < t["confidence_gate"]):
            errs.append(f"decision_path {path} needs confidence >= confidence_gate")
        cb = d.get("confidence_breakdown")
        if cb is not None:
            errs += _in_unit(cb["value"], "confidence_breakdown.value")
            if cb["value"] != d["confidence"] or cb["gate"] != t["confidence_gate"]:
                errs.append("confidence_breakdown must match confidence and thresholds.confidence_gate")
            for k, v in cb["components"].items():
                errs += _enum(k, CONFIDENCE_COMPONENTS, "confidence_breakdown.components key")
                errs += _in_unit(v, f"confidence_breakdown.components.{k}")
        fact_ids = [f["fact_id"] for f in d.get("facts", [])]
        if len(set(fact_ids)) != len(fact_ids):
            errs.append("facts: duplicate fact_id")
        for i, f in enumerate(d.get("facts", [])):
            w = f"facts[{i}]"
            errs += _enum(f["speaker"], SPEAKERS, f"{w}.speaker") + _enum(f["act"], FACT_ACTS, f"{w}.act")
            errs += _enum(f["info_type"], INFO_TYPES, f"{w}.info_type")
            if not f["segment_ids"]:
                errs.append(f"{w}.segment_ids must not be empty")
            if f.get("valid", True) == bool(f.get("drop_reason")):
                errs.append(f"{w}: drop_reason must be set exactly when valid is false")
        hit_ids = [h["hit_id"] for h in d.get("keyword_hits", [])]
        if len(set(hit_ids)) != len(hit_ids):
            errs.append("keyword_hits: duplicate hit_id")
        for i, h in enumerate(d.get("keyword_hits", [])):
            errs += _enum(h["family"], tuple(CRITERION_BY_FAMILY), f"keyword_hits[{i}].family")
            errs += _in_unit(h["score"], f"keyword_hits[{i}].score")
        for i, r in enumerate(d.get("rules", [])):
            w = f"rules[{i}]"
            errs += _enum(r["criterion"], CRITERIA, f"{w}.criterion") + _in_unit(r["risk"], f"{w}.risk")
            errs += [f"{w}: unknown fact_id {x}" for x in r.get("fact_ids", []) if x not in fact_ids]
            errs += [f"{w}: unknown keyword_hit_id {x}" for x in r.get("keyword_hit_ids", []) if x not in hit_ids]
        return errs


# --------------------------------------------------------------------------- AnalysisArtifact

FEATURE_MAP_STATUSES = ("not_computed", "ok", "error")


@dataclass
class Interval:
    start_s: float
    end_s: float


@dataclass
class EvidenceWindow:
    """Shaded on every audio lane. Indices point into CallResult.findings[f].evidence[e]."""
    start_s: float
    end_s: float
    criterion: str
    finding_index: int
    evidence_index: int


@dataclass
class WaveformPeaks:
    bucket_s: float
    min: list[float]                      # normalised amplitude, -1..1
    max: list[float]
    axes: dict[str, Axis]                 # x (s), y


@dataclass
class MelSpectrogram:
    times_s: list[float]                  # frame centres
    freqs_hz: list[float]                 # mel band centres, increasing
    db: list[list[float]]                 # rows = freqs_hz, columns = times_s
    db_min: float
    db_max: float
    axes: dict[str, Axis]                 # x (s), y (Hz, mel scale), value (dB) -> colour bar
    png_path: str | None = None


@dataclass
class SpeechActivity:
    intervals: list[Interval]
    axes: dict[str, Axis]                 # x (s)


@dataclass
class Turn:
    start_s: float
    end_s: float
    speaker: str
    segment_ids: list[str] = field(default_factory=list)


@dataclass
class Turns:
    items: list[Turn]
    axes: dict[str, Axis]                 # x (s)


@dataclass
class RatePoint:
    start_s: float
    end_s: float
    speaker: str
    value: float


@dataclass
class SpeechRate:
    points: list[RatePoint]
    axes: dict[str, Axis]                 # x (s), value (e.g. words/min)


@dataclass
class Contour:
    """Pitch or energy. `values[i]` belongs to `times_s[i]`; null = unvoiced / no estimate."""
    times_s: list[float]
    values: list[float | None]
    axes: dict[str, Axis]                 # x (s), value (Hz or dB)


@dataclass
class QualitySegment:
    segment_id: str
    start_s: float
    end_s: float
    snr_db: float
    score: float                          # 0-1, 1 = clean


@dataclass
class AudioQuality:
    """The only analysis block that feeds the decision (via the confidence gate)."""
    call_snr_db: float
    call_score: float
    segments: list[QualitySegment]
    axes: dict[str, Axis]                 # x (s), value (score 0-1)


@dataclass
class AsrConfidencePoint:
    segment_id: str
    start_s: float
    end_s: float
    avg_logprob: float
    no_speech_prob: float


@dataclass
class AsrConfidence:
    segments: list[AsrConfidencePoint]
    axes: dict[str, Axis]                 # x (s), value (avg log-prob)


@dataclass
class FeatureLayer:
    name: str                             # "conv1", "conv2", "block_<n>"
    pooling: str                          # how channels were reduced, e.g. "mean over 64-channel groups"
    shape: list[int]                      # [rows, cols] of values
    values: list[list[float]]             # normalised to [-1, 1]
    axes: dict[str, Axis]                 # x (s), y, value


@dataclass
class FeatureMapWindow:
    finding_index: int
    evidence_index: int
    start_s: float
    end_s: float
    layers: list[FeatureLayer]


@dataclass
class AnalysisVersions:
    analysis: str | None = None
    asr: str | None = None


@dataclass
class AnalysisArtifact(_Artifact):
    """Per-call audio analysis for the UI. Every block is optional: a missing block is a gap in the
    UI, never an invalid artifact and never a reason to change the decision."""
    call_id: str
    duration_s: float
    sample_rate: int
    evidence_windows: list[EvidenceWindow] = field(default_factory=list)
    waveform_peaks: WaveformPeaks | None = None
    mel_spectrogram: MelSpectrogram | None = None
    speech_activity: SpeechActivity | None = None
    turns: Turns | None = None
    speech_rate: SpeechRate | None = None
    pitch: Contour | None = None
    energy: Contour | None = None
    audio_quality: AudioQuality | None = None
    asr_confidence: AsrConfidence | None = None
    feature_maps: list[FeatureMapWindow] | None = None   # STRETCH, lazy (--feature-maps)
    feature_maps_status: str = "not_computed"
    audio_quality_cnn: dict[str, Any] | None = None      # optional later
    stage_errors: list[StageError] = field(default_factory=list)
    versions: AnalysisVersions = field(default_factory=AnalysisVersions)
    is_mock: bool = False
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def _semantic(cls, d: dict) -> list[str]:
        errs = _schema_version(d)
        dur = d["duration_s"]
        if dur <= 0 or d["sample_rate"] <= 0:
            return errs + ["duration_s and sample_rate must be positive"]
        for i, w in enumerate(d.get("evidence_windows", [])):
            errs += _span(w["start_s"], w["end_s"], dur, f"evidence_windows[{i}]")
            errs += _enum(w["criterion"], CRITERIA, f"evidence_windows[{i}].criterion")

        if (b := d.get("waveform_peaks")) is not None:
            errs += _axes(b["axes"], ("x", "y"), "waveform_peaks")
            if len(b["min"]) != len(b["max"]):
                errs.append("waveform_peaks: min and max must have the same length")
            if any(not -1 <= lo <= hi <= 1 for lo, hi in zip(b["min"], b["max"])):
                errs.append("waveform_peaks: need -1 <= min <= max <= 1 per bucket")
            if b["bucket_s"] <= 0 or abs(len(b["min"]) * b["bucket_s"] - dur) > b["bucket_s"]:
                errs.append("waveform_peaks: len(min) * bucket_s must cover duration_s")
        if (b := d.get("mel_spectrogram")) is not None:
            errs += _axes(b["axes"], ("x", "y", "value"), "mel_spectrogram")
            errs += _times(b["times_s"], dur, "mel_spectrogram.times_s")
            errs += _times(b["freqs_hz"], None, "mel_spectrogram.freqs_hz")
            if len(b["db"]) != len(b["freqs_hz"]) or any(len(r) != len(b["times_s"]) for r in b["db"]):
                errs.append("mel_spectrogram.db must be len(freqs_hz) rows x len(times_s) columns")
            elif any(not b["db_min"] <= x <= b["db_max"] for r in b["db"] for x in r):
                errs.append("mel_spectrogram.db values must lie in [db_min, db_max]")
        if (b := d.get("speech_activity")) is not None:
            errs += _axes(b["axes"], ("x",), "speech_activity")
            for i, iv in enumerate(b["intervals"]):
                errs += _span(iv["start_s"], iv["end_s"], dur, f"speech_activity.intervals[{i}]")
        if (b := d.get("turns")) is not None:
            errs += _axes(b["axes"], ("x",), "turns")
            for i, t in enumerate(b["items"]):
                errs += _span(t["start_s"], t["end_s"], dur, f"turns.items[{i}]")
                errs += _enum(t["speaker"], SPEAKERS, f"turns.items[{i}].speaker")
        if (b := d.get("speech_rate")) is not None:
            errs += _axes(b["axes"], ("x", "value"), "speech_rate")
            for i, p in enumerate(b["points"]):
                errs += _span(p["start_s"], p["end_s"], dur, f"speech_rate.points[{i}]")
                errs += _enum(p["speaker"], SPEAKERS, f"speech_rate.points[{i}].speaker")
        for k in ("pitch", "energy"):
            if (b := d.get(k)) is not None:
                errs += _axes(b["axes"], ("x", "value"), k) + _times(b["times_s"], dur, f"{k}.times_s")
                if len(b["values"]) != len(b["times_s"]):
                    errs.append(f"{k}: values and times_s must have the same length")
        if (b := d.get("audio_quality")) is not None:
            errs += _axes(b["axes"], ("x", "value"), "audio_quality") + _in_unit(b["call_score"], "audio_quality.call_score")
            for i, s in enumerate(b["segments"]):
                errs += _span(s["start_s"], s["end_s"], dur, f"audio_quality.segments[{i}]")
                errs += _in_unit(s["score"], f"audio_quality.segments[{i}].score")
        if (b := d.get("asr_confidence")) is not None:
            errs += _axes(b["axes"], ("x", "value"), "asr_confidence")
            for i, s in enumerate(b["segments"]):
                errs += _span(s["start_s"], s["end_s"], dur, f"asr_confidence.segments[{i}]")
                errs += _in_unit(s["no_speech_prob"], f"asr_confidence.segments[{i}].no_speech_prob")

        status, maps = d.get("feature_maps_status", "not_computed"), d.get("feature_maps")
        errs += _enum(status, FEATURE_MAP_STATUSES, "feature_maps_status")
        if (status == "ok") != (maps is not None):
            errs.append("feature_maps must be a list exactly when feature_maps_status is ok")
        for i, fm in enumerate(maps or []):
            w = f"feature_maps[{i}]"
            errs += _span(fm["start_s"], fm["end_s"], dur, w)
            for j, layer in enumerate(fm["layers"]):
                lw = f"{w}.layers[{j}]"
                errs += _axes(layer["axes"], ("x", "y", "value"), lw)
                vals = layer["values"]
                if layer["shape"] != [len(vals), len(vals[0]) if vals else 0] or any(len(r) != len(vals[0]) for r in vals):
                    errs.append(f"{lw}: shape must match values [rows, cols]")
                if any(not -1 <= x <= 1 for r in vals for x in r):
                    errs.append(f"{lw}: values must be normalised to [-1, 1]")
        return errs


# --------------------------------------------------------------------------- Inbox + SSE

VARIANTS = ("clean", "noisy", "unspecified")
CALL_STATUSES = ("queued", "processing", "done", "error")
STAGES = ("upload", "asr", "diarize", "keywords", "extract", "validate", "rules", "confidence",
          "decide", "narrate", "snippets", "analysis", "trigger")
EVENT_TYPES = ("job_queued", "stage_started", "stage_finished", "stage_failed", "job_finished")


@dataclass
class CallListItem(_Artifact):
    """One row of GET /api/calls. `status` is processing state; `error` = finished with stage errors."""
    call_id: str
    status: str
    duration_s: float | None = None
    variant: str | None = None            # from inference.json, not a label
    decision: str | None = None
    risk_score: float | None = None
    confidence: float | None = None
    criteria: list[str] = field(default_factory=list)   # criteria of the findings, risk-descending
    n_stage_errors: int = 0
    updated_at: str | None = None
    is_mock: bool = False

    @classmethod
    def _semantic(cls, d: dict) -> list[str]:
        errs = _enum(d["status"], CALL_STATUSES, "status")
        if d.get("variant") is not None:
            errs += _enum(d["variant"], VARIANTS, "variant")
        if d.get("decision") is not None:
            errs += _enum(d["decision"], DECISIONS, "decision")
        errs += _in_unit(d.get("risk_score"), "risk_score") + _in_unit(d.get("confidence"), "confidence")
        errs += [e for c in d.get("criteria", []) for e in _enum(c, CRITERIA, "criteria item")]
        if d["status"] in ("done", "error") and (d.get("decision") is None or d.get("risk_score") is None):
            errs.append(f"status {d['status']} needs decision and risk_score")
        if d["status"] == "error" and (d.get("decision") == "no_alert" or not d.get("n_stage_errors")):
            errs.append("status error needs n_stage_errors > 0 and a decision other than no_alert")
        return errs


@dataclass
class ProcessingEvent(_Artifact):
    """One SSE `data:` payload. `seq` increases per call; clients resume with Last-Event-ID."""
    seq: int
    event: str
    call_id: str
    ts: str                               # ISO 8601 UTC
    stage: str | None = None
    elapsed_s: float | None = None        # stage duration on stage_finished / stage_failed
    cached: bool | None = None            # stage result came from the cache
    message: str | None = None
    decision: str | None = None           # job_finished only

    @classmethod
    def _semantic(cls, d: dict) -> list[str]:
        errs = _enum(d["event"], EVENT_TYPES, "event")
        if d["event"].startswith("stage_"):
            errs += _enum(d.get("stage"), STAGES, "stage")
        if d["event"] == "stage_failed" and not d.get("message"):
            errs.append("stage_failed needs a message")
        if d["event"] == "job_finished":
            errs += _enum(d.get("decision"), DECISIONS, "decision")
        elif d.get("decision") is not None:
            errs.append("decision is only set on job_finished")
        return errs


# --------------------------------------------------------------------------- QualityReport

SPLITS = ("dev", "holdout", "test")
CONVENTIONS = ("strict_alarm", "escalation")
CURVE_PARAMS = ("alarm_threshold", "review_threshold", "confidence_gate")
ABLATIONS = ("keyword_only", "llm_only", "combined")


@dataclass
class Metric:
    """Point estimate with a bootstrap CI. None = undefined (e.g. no predicted positives)."""
    value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass
class BinaryMetrics:
    tp: int
    fp: int
    fn: int
    tn: int
    precision: Metric
    recall: Metric
    f1: Metric


@dataclass
class ThreeClassMetrics:
    labels: list[str]
    confusion: dict[str, dict[str, int]]   # rows = gold, columns = predicted (as in evaluate.py)
    macro_f1: Metric
    accuracy: Metric


@dataclass
class ConventionSet:
    """The three metric conventions, always reported together."""
    n: int
    strict_alarm: BinaryMetrics
    escalation: BinaryMetrics
    three_class: ThreeClassMetrics


@dataclass
class Bootstrap:
    n_resamples: int
    ci_level: float
    unit: str                              # resampling unit, e.g. "dialogue group"
    seed: int


@dataclass
class CurvePoint:
    threshold: float
    precision: float | None
    recall: float | None
    f1: float | None


@dataclass
class ThresholdCurve:
    param: str
    convention: str
    current: float                         # value in config/thresholds.json for this run
    points: list[CurvePoint]


@dataclass
class ReliabilityBin:
    lo: float
    hi: float
    n: int
    mean_confidence: float | None
    accuracy: float | None


@dataclass
class Reliability:
    correctness: str                       # what "correct" means, e.g. "3-class decision == gold"
    bins: list[ReliabilityBin]
    ece: Metric


@dataclass
class Ablation:
    name: str
    transcript: str                        # reference | asr
    conventions: ConventionSet


@dataclass
class WerBin:
    wer_lo: float
    wer_hi: float
    n: int                                 # gold-escalated calls in this WER bin
    escalation_recall: Metric


@dataclass
class StageLatency:
    stage: str
    n: int
    mean_s: float
    p50_s: float
    p95_s: float


@dataclass
class EvidenceValiditySummary:
    n_items: int
    n_valid_items: int
    item_validity_rate: float | None
    per_check_pass_rate: dict[str, float]
    checks_skipped: list[str] = field(default_factory=list)


@dataclass
class QualityReport(_Artifact):
    report_id: str
    created_at: str
    run_id: str
    system: str
    provider: str
    mode: str
    split: str
    bootstrap: Bootstrap
    overall: ConventionSet
    breakdowns: dict[str, dict[str, ConventionSet]] = field(default_factory=dict)  # stufe, variant
    threshold_curves: list[ThresholdCurve] = field(default_factory=list)
    reliability: Reliability | None = None
    ablations: list[Ablation] = field(default_factory=list)
    wer_vs_recall: list[WerBin] = field(default_factory=list)
    latency: list[StageLatency] = field(default_factory=list)
    evidence_validity: EvidenceValiditySummary | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    is_mock: bool = False
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def _semantic(cls, d: dict) -> list[str]:
        errs = _schema_version(d) + _enum(d["mode"], MODES, "mode") + _enum(d["split"], SPLITS, "split")
        b = d["bootstrap"]
        if b["n_resamples"] < 1 or not 0 < b["ci_level"] < 1:
            errs.append("bootstrap: need n_resamples >= 1 and 0 < ci_level < 1")
        errs += _convention_set(d["overall"], "overall")
        n = d["overall"]["n"]
        for key, groups in d.get("breakdowns", {}).items():
            for g, cs in groups.items():
                errs += _convention_set(cs, f"breakdowns.{key}.{g}")
            if sum(cs["n"] for cs in groups.values()) != n:
                errs.append(f"breakdowns.{key}: group sizes must add up to overall.n")
        for i, c in enumerate(d.get("threshold_curves", [])):
            w = f"threshold_curves[{i}]"
            errs += _enum(c["param"], CURVE_PARAMS, f"{w}.param") + _enum(c["convention"], CONVENTIONS, f"{w}.convention")
            errs += _in_unit(c["current"], f"{w}.current") + _times([p["threshold"] for p in c["points"]], 1.0, f"{w}.points.threshold")
            errs += [e for j, p in enumerate(c["points"]) for k in ("precision", "recall", "f1")
                     for e in _in_unit(p[k], f"{w}.points[{j}].{k}")]
        if (r := d.get("reliability")) is not None:
            errs += _metric(r["ece"], "reliability.ece")
            bins = r["bins"]
            if bins and (bins[0]["lo"] != 0 or bins[-1]["hi"] != 1 or any(a["hi"] != b["lo"] for a, b in zip(bins, bins[1:]))):
                errs.append("reliability.bins must tile [0, 1] without gaps")
            if sum(x["n"] for x in bins) > n:
                errs.append("reliability.bins hold more calls than overall.n")
        for i, a in enumerate(d.get("ablations", [])):
            errs += _enum(a["name"], ABLATIONS, f"ablations[{i}].name") + _enum(a["transcript"], MODES, f"ablations[{i}].transcript")
            errs += _convention_set(a["conventions"], f"ablations[{i}].conventions")
        for i, w in enumerate(d.get("wer_vs_recall", [])):
            if not 0 <= w["wer_lo"] < w["wer_hi"]:
                errs.append(f"wer_vs_recall[{i}]: need 0 <= wer_lo < wer_hi")
            errs += _metric(w["escalation_recall"], f"wer_vs_recall[{i}].escalation_recall")
        for i, s in enumerate(d.get("latency", [])):
            errs += _enum(s["stage"], STAGES, f"latency[{i}].stage")
            if not 0 <= s["p50_s"] <= s["p95_s"] or s["mean_s"] < 0:
                errs.append(f"latency[{i}]: need 0 <= p50_s <= p95_s and mean_s >= 0")
        if (ev := d.get("evidence_validity")) is not None:
            if not 0 <= ev["n_valid_items"] <= ev["n_items"]:
                errs.append("evidence_validity: need 0 <= n_valid_items <= n_items")
            errs += _in_unit(ev["item_validity_rate"], "evidence_validity.item_validity_rate")
            errs += [e for k, v in ev["per_check_pass_rate"].items() for e in _in_unit(v, f"evidence_validity.per_check_pass_rate.{k}")]
        return errs


def _metric(m: dict, where: str) -> list[str]:
    errs = [e for k in ("value", "ci_low", "ci_high") for e in _in_unit(m.get(k), f"{where}.{k}")]
    lo, hi = m.get("ci_low"), m.get("ci_high")
    if (lo is None) != (hi is None):
        errs.append(f"{where}: ci_low and ci_high must both be set or both be null")
    elif lo is not None and not lo <= hi:
        errs.append(f"{where}: need ci_low <= ci_high")
    # No value-inside-CI check: percentile bootstrap CIs may exclude the point estimate at small n.
    return errs


def _convention_set(cs: dict, where: str) -> list[str]:
    errs = []
    for conv in CONVENTIONS:
        bm = cs[conv]
        if bm["tp"] + bm["fp"] + bm["fn"] + bm["tn"] != cs["n"]:
            errs.append(f"{where}.{conv}: tp+fp+fn+tn must equal n")
        errs += [e for k in ("precision", "recall", "f1") for e in _metric(bm[k], f"{where}.{conv}.{k}")]
    tc = cs["three_class"]
    if tuple(tc["labels"]) != DECISIONS or set(tc["confusion"]) != set(DECISIONS) \
            or any(set(row) != set(DECISIONS) for row in tc["confusion"].values()):
        errs.append(f"{where}.three_class: labels and confusion must use exactly {DECISIONS}")
    elif sum(x for row in tc["confusion"].values() for x in row.values()) != cs["n"]:
        errs.append(f"{where}.three_class.confusion must sum to n")
    errs += _metric(tc["macro_f1"], f"{where}.three_class.macro_f1") + _metric(tc["accuracy"], f"{where}.three_class.accuracy")
    return errs
