"""process_call: the whole pipeline for one call (implementation behind `pipeline.process_call`).

    audio_analysis -> asr | reference -> keywords + extraction -> decide -> snippets -> narrate -> trigger

Never raises for stage failures: they come back in `stage_errors` with decision `review`. Even an unexpected
exception becomes a `review` result with StageError("pipeline"). `on_event` is fire-and-forget: it receives
ProcessingEvent-shaped dicts (without `seq`); if it raises, the pipeline logs once and carries on.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pipeline import decide as dec
from pipeline import narrate as nar
from pipeline import snippets as snip
from pipeline import stages
from pipeline import trigger as trg
from pipeline.io import write_json_atomic
from pipeline.schemas import (CallResult, DecisionTrace, Finding, StageError, Transcript, Versions,
                              validate_call_result)

REPO_ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("sentinel.pipeline")
CALL_ID = re.compile(r"^[A-Za-z0-9_]+$")
NO_LLM_VERSION = "none (--no-llm: keywords + rules only)"


class _Events:
    """Emits stage events; a raising callback is logged once and never affects the pipeline."""

    def __init__(self, call_id: str, cb: Callable[[dict], None] | None):
        self.call_id, self.cb, self.warned = call_id, cb, False

    def emit(self, event: str, **kw) -> None:
        if self.cb is None:
            return
        d = {"event": event, "call_id": self.call_id, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             **{k: v for k, v in kw.items() if v is not None}}
        try:
            self.cb(d)
        except Exception as exc:
            if not self.warned:
                self.warned = True
                log.warning("%s: on_event callback raised %s: %s (further callback errors are not logged)",
                            self.call_id, type(exc).__name__, exc)

    def stage(self, name: str, fn, cached: Callable[[object], bool] | None = None):
        """Run fn() -> (value, errors, ...); emit started/finished|failed around it. Returns fn's tuple."""
        self.emit("stage_started", stage=name)
        t0 = time.perf_counter()
        res = fn()
        errs = next((x for x in res if isinstance(x, list) and x and isinstance(x[0], StageError)), [])
        dt = round(time.perf_counter() - t0, 3)
        if errs:
            self.emit("stage_failed", stage=name, elapsed_s=dt, message="; ".join(e.message for e in errs)[:500])
        else:
            self.emit("stage_finished", stage=name, elapsed_s=dt, cached=cached(res) if cached else None)
        return res


def _paths(artifacts_dir: Path | None, out_dir: Path | None, mode: str) -> dict[str, Path]:
    a = Path(artifacts_dir) if artifacts_dir else REPO_ROOT / "artifacts"
    o = Path(out_dir) if out_dir else REPO_ROOT / "out"
    sfx = "" if mode == "asr" else "_reference"      # reference runs never overwrite ASR transcripts or traces
    return {"analysis": a / "analysis", "transcripts": a / f"transcripts{sfx}", "traces": a / f"traces{sfx}",
            "cache": a / "cache" / "asr", "results": o / "results", "snippets": o / "snippets", "judge": o / "judge",
            "triggers": o / "triggers"}


def _decision_source() -> str:
    """config/thresholds.json "decision_source": "direct_judge" (S4 decides) or "rules" (facts -> rules, default)."""
    try:
        return json.loads((dec.CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8")).get("decision_source", "rules")
    except Exception:
        return "rules"


def _escalate(trace: DecisionTrace, findings: list[Finding]) -> str:
    """no_alert -> review after a stage error. Rewrites the trace (decision, path) and regenerates the narrative and
    why-not texts from it, so trace, result and narrative never disagree. Returns the new narrative."""
    trace.decision, trace.decision_path = "review", "stage_error"
    try:
        narrative, trace.why_not_flagged, trace.what_would_change = nar.narrate(trace, findings)
    except Exception:
        narrative = f"{nar.TEMPLATE_TAG} Decision review (a stage failed); needs human review."
    return narrative


def _escalate_result(result: CallResult, trace: DecisionTrace | None) -> None:
    result.decision = "review"
    if trace is not None:
        result.narrative = _escalate(trace, result.findings)
    else:
        result.narrative = f"{nar.TEMPLATE_TAG} Decision review (a stage failed); needs human review."


def _failed_result(call_id: str, errors: list[StageError], versions: Versions | None = None) -> CallResult:
    return CallResult(call_id=call_id, decision="review", risk_score=0.0, confidence=None,
                      narrative=f"{nar.TEMPLATE_TAG} Processing failed ({errors[0].stage}); needs human review.",
                      stage_errors=errors, versions=versions or Versions())


def process_call(audio_path: str, call_id: str, *, on_event: Callable[[dict], None] | None = None,
                 transcripts: str = "asr", no_llm: bool = False, config: dec.Config | None = None,
                 artifacts_dir: Path | None = None, out_dir: Path | None = None, trigger: bool = True) -> dict:
    if not CALL_ID.fullmatch(call_id or ""):
        raise ValueError(f"call_id must match {CALL_ID.pattern!r}, got {call_id!r}")
    if transcripts not in ("asr", "reference"):
        raise ValueError("transcripts must be 'asr' or 'reference'")
    ev = _Events(call_id, on_event)
    P = _paths(artifacts_dir, out_dir, transcripts)
    t_start = time.perf_counter()
    trace = None
    try:
        result, trace = _run(audio_path, call_id, ev, P, transcripts, no_llm, config, trigger)
    except Exception as exc:     # last line of defence: unknown failure is review, never no_alert, never a raise
        log.exception("%s: unexpected pipeline failure", call_id)
        result = _failed_result(call_id, stages._err("pipeline", exc))

    trace_path = P["traces"] / f"{call_id}.json"
    if trace is not None:
        try:
            write_json_atomic(trace_path, trace.to_dict())
        except Exception as exc:
            log.error("%s: cannot write trace: %s", call_id, exc)
            result.stage_errors += stages._err("trace", exc)
            if result.decision == "no_alert":
                _escalate_result(result, trace)
    problems = validate_call_result(result.to_dict())
    if problems:      # a schema-invalid result must not leave the pipeline looking healthy
        result = _failed_result(call_id, result.stage_errors + [StageError("pipeline", f"invalid result: {problems[:3]}")],
                                result.versions)
        trace = None
    try:
        write_json_atomic(P["results"] / f"{call_id}.json", result.to_dict())
    except Exception as exc:      # the API reads this file: not persisting is a failed stage, never a healthy no_alert
        log.error("%s: cannot write result file: %s", call_id, exc)
        result.stage_errors += stages._err("results", exc)
        if result.decision == "no_alert":
            _escalate_result(result, trace)
            if trace is not None:
                try:
                    write_json_atomic(trace_path, trace.to_dict())      # best effort: keep trace and result in step
                except Exception as exc2:
                    log.error("%s: cannot rewrite trace: %s", call_id, exc2)
    ev.emit("job_finished", decision=result.decision, elapsed_s=round(time.perf_counter() - t_start, 3))
    return result.to_dict()


def _run(audio_path, call_id, ev: _Events, P, mode, no_llm, config, do_trigger) -> tuple[CallResult, DecisionTrace | None]:
    errors: list[StageError] = []        # errors that go into CallResult.stage_errors
    try:
        config = config or dec.load_config()
    except Exception as exc:
        return _failed_result(call_id, stages._err("config", exc)), None

    analysis, _, _ = ev.stage("analysis", lambda: stages.run_analysis(audio_path, call_id, P["analysis"]),
                              cached=lambda r: r[2])       # optional: its errors never touch the decision

    if mode == "asr":
        transcript, errs = ev.stage("asr", lambda: stages.run_asr(
            audio_path, call_id, transcripts_dir=P["transcripts"], analysis_dir=P["analysis"], cache_dir=P["cache"]))
    else:
        transcript, errs = ev.stage("asr", lambda: stages.run_reference(call_id))
    errors += errs
    if mode == "asr" and transcript is not None and analysis is not None:
        analysis = stages.load_analysis(call_id, P["analysis"]) or analysis    # ASR merged its block into the file
    if transcript is None:
        transcript = Transcript(call_id=call_id, mode=mode, segments=[])
    elif mode == "reference":
        try:
            write_json_atomic(P["transcripts"] / f"{call_id}.json", transcript.to_dict())
        except Exception as exc:
            log.warning("%s: cannot write reference transcript: %s", call_id, exc)

    versions = Versions(asr=transcript.asr_model or ("reference-transcript" if mode == "reference" else None))
    facts = None
    if errors:
        pass                                         # no transcript: skip extraction, the decision is review
    elif no_llm:
        facts, versions.llm = [], NO_LLM_VERSION     # explicit, labelled ablation: not a stage error
    else:
        facts, errs, vinfo = ev.stage("extract", lambda: stages.run_extraction(transcript, call_id))
        errors += errs
        versions.llm, versions.prompt = vinfo.get("llm"), vinfo.get("prompt")
        versions.provider, versions.self_hosted = vinfo.get("provider"), vinfo.get("self_hosted")

    ev.emit("stage_started", stage="decide")
    trace, errs = stages.run_decision(transcript, facts, analysis, config, errors, versions)
    if trace is None:
        ev.emit("stage_failed", stage="decide", message="; ".join(e.message for e in errs)[:500])
        return _failed_result(call_id, errors + errs, versions), None
    for name in ("keywords", "rules", "confidence", "decide"):
        ev.emit("stage_finished", stage=name, elapsed_s=round(trace.timings_s.get(name, 0.0), 3))

    judged = None
    if not errors and _decision_source() == "direct_judge":
        judged, errs = ev.stage("judge", lambda: stages.run_judge(transcript))
        errors += errs
        if judged is not None:
            stages.apply_judge(trace, judged)
            write_json_atomic(P["judge"] / f"{call_id}.json", judged.to_dict())
    findings = stages.judge_findings(judged, transcript) if judged is not None else stages.build_findings(trace, transcript)
    audio_ok = mode == "asr" and transcript.duration_s is not None
    if trace.decision != "no_alert" and audio_ok:
        _, errs = ev.stage("snippets", lambda: (None, snip.cut_snippets(audio_path, call_id, findings,
                                                                        transcript.duration_s, P["snippets"])))
        errors += errs
    if audio_ok:
        stages.add_evidence_windows(analysis, findings, P["analysis"])   # display only

    ev.emit("stage_started", stage="narrate")
    try:
        narrative, why, change = nar.narrate(trace, findings)
        trace.why_not_flagged, trace.what_would_change = why, change
        ev.emit("stage_finished", stage="narrate", elapsed_s=0.0)
    except Exception as exc:
        narrative = f"{nar.TEMPLATE_TAG} narrative failed."
        errors += stages._err("narrate", exc)
        ev.emit("stage_failed", stage="narrate", message=str(exc)[:500])

    if do_trigger and trace.decision == "alarm":
        _, errs = ev.stage("trigger", lambda: (None, trg.send_triggers(call_id, trace.decision, findings, P["triggers"])[1]))
        errors += errs

    if errors and trace.decision == "no_alert":    # hard rule: a failed stage is never a silent no_alert
        narrative = _escalate(trace, findings)
    return CallResult(call_id=call_id, decision=trace.decision, risk_score=trace.risk_score, confidence=trace.confidence,
                      findings=findings, narrative=narrative, stage_errors=errors, versions=trace.versions), trace
