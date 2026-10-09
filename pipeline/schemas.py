"""Output contract for one processed call. Source of truth for the API, web app and evaluation.

Stdlib dataclasses only (no pydantic in the pipeline venv). `CallResult.from_dict` validates and
raises `SchemaError` with every problem found; `validate_call_result` returns the list instead.

Per call:
  call_id, decision (alarm | review | no_alert), risk_score 0-1, confidence 0-1 (None = not computed),
  findings[] {criterion, risk, reason, evidence[], counter_evidence[]},
  evidence item {segment_ids, start_s, end_s, speaker, text, snippet_path},
  narrative, stage_errors[] {stage, message}, versions {asr, llm, prompt, rules}.

A predictions file (`artifacts/predictions/<run>.json`) wraps the per-call results in a `RunResult`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
    for i, f in enumerate(d.get("findings", []) or []):
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
    stage_errors = d.get("stage_errors", []) or []
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
