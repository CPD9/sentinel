"""Thin stage wrappers for process_call. Each returns (value, [StageError]) and NEVER raises: a failed stage is
a recorded StageError (and the decision becomes `review`), never a silent no_alert.

Extraction is built in a parallel branch (pipeline/extract.py). It is imported lazily here; this module never
creates it. Assumed contract, adjust when that branch lands:

    pipeline.extract.extract_facts(transcript: Transcript) -> list[schemas.Fact]   # validated facts (valid flag set)
    pipeline.extract.VERSIONS = {"llm": "<model>@<rev>", "prompt": "<prompt version>",
                                 "provider": "<provider name>", "self_hosted": True}   # optional, recorded in versions

A missing module, an unreachable LLM_BASE_URL (probed first, 10 s) or any exception becomes StageError("extract").
"""
from __future__ import annotations

import importlib
from pathlib import Path

from pipeline import decide as dec
from pipeline.reference import reference_transcript
from pipeline.schemas import (AnalysisArtifact, DecisionTrace, EvidenceWindow, Evidence, Fact, Finding, StageError,
                              Transcript, TranscriptSegment, Versions)

COUNTER_ACTS = ("warn", "refuse", "hypothetical", "quote")
MAX_KEYWORD_EVIDENCE = 3


def _err(stage: str, exc: BaseException) -> list[StageError]:
    return [StageError(stage, f"{type(exc).__name__}: {exc}")]


# --------------------------------------------------------------------------- analysis, transcript

# pipeline.audio_analysis needs numpy (requirements-analysis.txt). It is optional, so it is imported inside the
# functions below: a missing dependency becomes a recorded analysis error, never an ImportError at import time.

def load_analysis(call_id: str, analysis_dir: Path) -> AnalysisArtifact | None:
    import json

    from pipeline import audio_analysis as aa
    p = aa.analysis_path(call_id, analysis_dir)
    try:
        return AnalysisArtifact.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def run_analysis(audio_path: str | Path, call_id: str, analysis_dir: Path
                 ) -> tuple[AnalysisArtifact | None, list[StageError], bool]:
    """CPU audio analysis; reuses the stored artifact when audio hash and analysis version match.
    Returns (artifact, errors, cached). Optional stage: its errors never touch the decision."""
    try:
        from pipeline import audio_analysis as aa
        path = Path(audio_path)
        if not path.is_absolute():
            path = aa.REPO_ROOT / path
        old = None
        target = aa.analysis_path(call_id, analysis_dir)
        if target.is_file():
            try:
                import json
                old = AnalysisArtifact.from_dict(json.loads(target.read_text(encoding="utf-8")))
            except Exception:
                old = None
        sha = aa.sha256_file(path)
        if old is not None and old.versions.analysis == aa.ANALYSIS_VERSION and old.audio_sha256 == sha:
            return old, [], True
        art = aa.analyze_call(path, call_id)
        if old is not None:
            aa._carry_over_asr(art, old)
        aa.save_analysis(art, analysis_dir)
        return art, [], False
    except Exception as exc:
        return None, _err("analysis", exc), False


def run_asr(audio_path: str | Path, call_id: str, **kw) -> tuple[Transcript | None, list[StageError]]:
    from pipeline import asr
    return asr.run_stage(audio_path, call_id, **kw)


def run_reference(call_id: str) -> tuple[Transcript | None, list[StageError]]:
    """Organizer scripts as transcript: segment ids are turn ids, no timestamps (dev evaluation without ASR)."""
    try:
        turns = reference_transcript(call_id)
        segs = [TranscriptSegment(id=t["segment_id"], speaker=t["speaker"], text=t["text"]) for t in turns]
        t = Transcript(call_id=call_id, mode="reference", segments=segs,
                       notes=["reference transcript (organizer script), no timestamps"])
        errs = Transcript.validate(t.to_dict())
        if errs:
            raise ValueError(f"invalid reference Transcript: {errs[:3]}")
        return t, []
    except Exception as exc:
        return None, _err("asr", exc)


# --------------------------------------------------------------------------- extraction

def run_extraction(transcript: Transcript, call_id: str) -> tuple[list[Fact] | None, list[StageError], dict]:
    """(facts, errors, versions). facts is None exactly when errors is non-empty.

    `versions` is returned on failure too: once a client has been chosen, its provider / self_hosted stay recorded,
    so a failed call to a remote provider remains auditable.
    """
    mod, vinfo = None, {}
    try:
        mod = importlib.import_module("pipeline.extract")
        from pipeline import llm
        client = llm.from_env()
        vinfo = _provenance(client)
        client.probe()                  # fail fast on a dead SSH tunnel instead of waiting out a 300 s timeout
        facts = mod.extract_facts(transcript)
        if not isinstance(facts, list) or not all(isinstance(f, Fact) for f in facts):
            raise TypeError("extract_facts must return list[Fact]")
        return facts, [], {**vinfo, **dict(getattr(mod, "VERSIONS", None) or {})}
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        partial = {k: v for k, v in dict(getattr(mod, "VERSIONS", None) or {}).items() if v is not None}
        # the module-level VERSIONS may be stale (set by an earlier call): the client chosen for THIS call wins
        return None, _err("extract", exc), {**partial, **vinfo}


def _provenance(client) -> dict:
    """provider + self_hosted of a client, {} when it carries no provider spec (e.g. a test double)."""
    spec = getattr(client, "spec", None)
    if spec is None:
        return {}
    return {"provider": spec.name, "self_hosted": spec.self_hosted}


# --------------------------------------------------------------------------- decision

def run_decision(transcript: Transcript, facts: list[Fact] | None, analysis: AnalysisArtifact | None,
                 config: dec.Config, stage_errors: list[StageError], versions: Versions
                 ) -> tuple[DecisionTrace | None, list[StageError]]:
    try:
        return dec.decide_call(transcript, facts, analysis, config, stage_errors=stage_errors, versions=versions), []
    except Exception as exc:
        return None, _err("decide", exc)


def _span(transcript: Transcript, ids: list[str]) -> tuple[float | None, float | None]:
    by_id = {s.id: s for s in transcript.segments}
    segs = [by_id[i] for i in ids if i in by_id and by_id[i].start_s is not None]
    if not segs:
        return None, None
    return min(s.start_s for s in segs), max(s.end_s for s in segs)


def run_judge(transcript: Transcript):
    """(JudgeResult | None, errors): the S4 direct judge with validated citations (pipeline/judge.py)."""
    from pipeline import judge
    try:
        return judge.judge_call(transcript), []
    except Exception as exc:
        return None, _err("judge", exc)


def judge_findings(result, transcript: Transcript, trace: DecisionTrace | None = None) -> list[Finding]:
    """Findings for a judge-decided call: the judge's verdict as one finding whose evidence is its VALIDATED citations
    (they drive the snippets). With `trace`: none for no_alert; keyword_review (or a review without a validated
    citation) points at the rules' evidence, which includes the keyword passages."""
    if trace is not None:
        if trace.decision == "no_alert":
            return []
        if trace.decision_path == "keyword_review" or not result.valid_citations:
            return build_findings(trace, transcript)
    elif result.decision == "no_alert":
        return []
    text = {s.id: s.text for s in transcript.segments}
    ev = []
    for c in result.valid_citations:
        s, e = _span(transcript, c.segment_ids)
        ev.append(Evidence(segment_ids=list(c.segment_ids), speaker=c.speaker,
                           text=c.quote or " ".join(text.get(i, "") for i in c.segment_ids), start_s=s, end_s=e))
    return [Finding(result.criterion, result.risk, f"Direct judge: {result.reason}", ev, [])]


def apply_judge(trace: DecisionTrace, result, config=None) -> None:
    """Thresholded judge decision (decide.judge_decide). Without a config: the old verdict rule (kept for callers)."""
    if config is not None:
        from pipeline import decide as dec
        dec.judge_decide(trace, result.to_dict(), config)
        return
    _apply_verdict(trace, result)


def _apply_verdict(trace: DecisionTrace, result) -> None:
    """The judge's verdict decides (decision_source "direct_judge"): an alarm needs >= 1 validated citation, else it
    is a review, never an alarm; so is an alarm below the confidence gate. Facts, rules and the confidence breakdown stay in the trace as the why."""
    decision = result.decision
    low_conf = trace.confidence is None or trace.confidence < trace.thresholds.confidence_gate
    if decision == "alarm" and (not result.valid_citations or low_conf):
        decision = "review"                   # never a confident alarm without validated evidence and confidence
    trace.decision, trace.decision_path, trace.risk_score = decision, f"judge_{decision}", result.risk


def build_findings(trace: DecisionTrace, transcript: Transcript) -> list[Finding]:
    """Rules with risk > 0 -> findings, risk-descending. Evidence comes from the rule's valid facts (counter acts go
    to counter_evidence), else from keyword hits (so a keyword-only risk still points at the passage)."""
    facts = {f.fact_id: f for f in trace.facts}
    hits = {h.hit_id: h for h in trace.keyword_hits}
    seg_speaker = {s.id: s.speaker for s in transcript.segments}

    def ev(ids: list[str], speaker: str, text: str) -> Evidence:
        s, e = _span(transcript, ids)
        return Evidence(segment_ids=list(ids), speaker=speaker, text=text, start_s=s, end_s=e)

    out = []
    for r in sorted(trace.rules, key=lambda r: -r.risk):
        if r.risk <= 0:
            continue
        evidence, counter = [], []
        for fid in r.fact_ids:
            f = facts.get(fid)
            if f is None or not f.valid:
                continue
            (counter if f.act in COUNTER_ACTS else evidence).append(ev(f.segment_ids, f.speaker, f.quote))
        if not evidence and r.keyword_hit_ids:
            seen = set()
            for hid in r.keyword_hit_ids:
                h = hits[hid]
                if h.segment_id in seen:
                    continue
                seen.add(h.segment_id)
                evidence.append(ev([h.segment_id], seg_speaker.get(h.segment_id, "unknown"), h.matched_text))
                if len(evidence) == MAX_KEYWORD_EVIDENCE:
                    break
        out.append(Finding(r.criterion, r.risk, r.reason, evidence, counter))
    return out


def add_evidence_windows(art: AnalysisArtifact | None, findings: list[Finding], analysis_dir: Path) -> list[StageError]:
    """Shade the evidence windows on the audio lanes. Display only; never feeds the decision."""
    if art is None:
        return []
    try:
        from pipeline import audio_analysis as aa
        wins = [EvidenceWindow(e.start_s, min(e.end_s, art.duration_s), f.criterion, fi, ei)
                for fi, f in enumerate(findings) for ei, e in enumerate(f.evidence)
                if e.start_s is not None and e.start_s < art.duration_s]
        art.evidence_windows = wins
        aa.save_analysis(art, analysis_dir)
        return []
    except Exception as exc:
        return _err("analysis", exc)
