"""Milestone 2 / 2.5: output contract and side-artifact schemas in pipeline/schemas.py."""
import copy
import json
from pathlib import Path

import pytest

from pipeline.schemas import (
    AnalysisArtifact, CallListItem, CallResult, DecisionTrace, ProcessingEvent, QualityReport, RunResult,
    SchemaError, Transcript, validate_call_result,
)


def call(**over):
    d = {
        "call_id": "call_001", "decision": "alarm", "risk_score": 0.9, "confidence": 0.8,
        "findings": [{"criterion": "insider_trading", "risk": 0.9, "reason": "r",
                      "evidence": [{"segment_ids": ["s1"], "start_s": 1.0, "end_s": 4.5, "speaker": "customer",
                                    "text": "nöd öffentlich", "snippet_path": "out/snippets/a.wav"}],
                      "counter_evidence": []}],
        "narrative": "n", "stage_errors": [],
        "versions": {"asr": "a", "llm": "l", "prompt": "p", "rules": "r"},
    }
    d.update(over)
    return d


def test_valid_roundtrip():
    c = CallResult.from_dict(call())
    assert c.to_dict() == call()


def test_reference_mode_evidence_without_timestamps_is_valid():
    d = call()
    d["findings"][0]["evidence"][0].update(start_s=None, end_s=None, snippet_path=None)
    assert validate_call_result(d) == []


@pytest.mark.parametrize("over, fragment", [
    ({"decision": "maybe"}, "decision"),
    ({"risk_score": 1.5}, "risk_score"),
    ({"confidence": -0.1}, "confidence"),
    ({"decision": "no_alert", "stage_errors": [{"stage": "asr", "message": "boom"}]}, "stage_errors"),
    ({"versions": {"foo": "x"}}, "versions"),
])
def test_invalid_call(over, fragment):
    errs = validate_call_result(call(**over))
    assert any(fragment in e for e in errs), errs


def test_invalid_evidence():
    d = call()
    d["findings"][0]["evidence"][0].update(start_s=5.0, end_s=2.0, speaker="boss", segment_ids=[])
    errs = validate_call_result(d)
    assert len(errs) == 3, errs
    with pytest.raises(SchemaError):
        CallResult.from_dict(d)


def test_run_result_rejects_duplicates_and_bad_mode():
    d = {"schema_version": 1, "run_id": "r", "mode": "audio", "system": "s", "provider": "p",
         "created_at": "now", "calls": [call(), call()]}
    with pytest.raises(SchemaError) as e:
        RunResult.from_dict(d)
    assert any("mode" in x for x in e.value.errors)
    assert any("duplicate" in x for x in e.value.errors)


@pytest.mark.parametrize("bad, type_name", [(None, "NoneType"), ({}, "dict"), ("x", "str")])
def test_findings_must_be_a_list(bad, type_name):
    d = call(findings=bad)
    assert validate_call_result(d) == [f"findings must be a list, got {type_name}"]
    with pytest.raises(SchemaError) as e:
        CallResult.from_dict(d)
    assert "findings must be a list" in str(e.value)


@pytest.mark.parametrize("bad, type_name", [(None, "NoneType"), ({}, "dict"), ("x", "str")])
def test_stage_errors_must_be_a_list(bad, type_name):
    d = call(stage_errors=bad)
    assert validate_call_result(d) == [f"stage_errors must be a list, got {type_name}"]
    with pytest.raises(SchemaError) as e:
        CallResult.from_dict(d)
    assert "stage_errors must be a list" in str(e.value)


def test_stage_errors_missing_defaults_to_empty():
    d = call()
    del d["stage_errors"]
    assert validate_call_result(d) == []
    assert CallResult.from_dict(d).stage_errors == []


def test_findings_valid_list():
    assert validate_call_result(call(findings=[])) == []
    assert len(CallResult.from_dict(call()).findings) == 1


# --------------------------------------------------------------------------- Milestone 2.5 side artifacts
FIX = Path(__file__).resolve().parents[1] / "fixtures"


def fx(name):
    return copy.deepcopy(json.loads((FIX / name).read_text(encoding="utf-8")))


def errs_after(schema, name, mutate):
    d = fx(name)
    mutate(d)
    return schema.validate(d)


def test_typed_check_reports_unknown_missing_and_wrong_types():
    d = fx("call_MOCK_001.transcript.json")
    d["extra"] = 1
    del d["mode"]
    d["segments"][0]["start_s"] = "0.8"
    errs = Transcript.validate(d)
    assert "extra: unknown key" in errs and "mode is required" in errs
    assert "segments[0].start_s must be float, got str" in errs
    with pytest.raises(SchemaError):
        Transcript.from_dict(d)


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d["segments"][1].update(id="s001"), "duplicate id"),
    (lambda d: d["segments"][0].update(start_s=None, end_s=None), "asr segments need start_s"),
    (lambda d: d["segments"][-1].update(end_s=999.0), "beyond audio duration"),
    (lambda d: d["segments"][0].update(speaker="banker"), "speaker"),
])
def test_transcript_semantics(mutate, fragment):
    assert any(fragment in e for e in errs_after(Transcript, "call_MOCK_001.transcript.json", mutate))


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.update(decision="review"), "cannot produce decision"),
    (lambda d: d.update(risk_score=0.5), "below the alarm threshold"),
    (lambda d: d.update(confidence=0.3), "needs confidence >= confidence_gate"),
    (lambda d: d["thresholds"].update(review=0.8), "review < alarm"),
    (lambda d: d["facts"][4].update(drop_reason=None), "drop_reason must be set exactly when valid is false"),
    (lambda d: d["rules"][0]["fact_ids"].append("F99"), "unknown fact_id F99"),
    (lambda d: d["keyword_hits"][0].update(family="gossip"), "family"),
    (lambda d: d["confidence_breakdown"]["components"].update(vibes=0.5), "components key"),
])
def test_decision_trace_semantics(mutate, fragment):
    assert any(fragment in e for e in errs_after(DecisionTrace, "call_MOCK_001.trace.json", mutate))


def _feature_window():
    layer = {"name": "conv1", "pooling": "mean over 64-channel groups", "shape": [2, 3],
             "values": [[-1.0, 0.0, 0.5], [0.2, 0.9, -0.3]],
             "axes": {"x": {"label": "time", "unit": "s"}, "y": {"label": "channel group", "unit": "index"},
                      "value": {"label": "activation", "unit": "normalised (-1..1)"}}}
    return {"finding_index": 0, "evidence_index": 0, "start_s": 82.3, "end_s": 107.8, "layers": [layer]}


def test_analysis_feature_maps_stretch_shape_is_valid():
    d = fx("call_MOCK_001.analysis.json")
    d.update(feature_maps=[_feature_window()], feature_maps_status="ok")
    assert AnalysisArtifact.validate(d) == []
    assert AnalysisArtifact.from_dict(d).feature_maps[0].layers[0].shape == [2, 3]


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d["mel_spectrogram"]["axes"]["value"].update(unit=" "), "axes.value.unit must be non-empty"),
    (lambda d: d["mel_spectrogram"]["axes"].pop("value"), "mel_spectrogram.axes.value is required"),
    (lambda d: d["turns"]["axes"]["x"].update(unit="ms"), "share one time axis"),
    (lambda d: d["evidence_windows"][0].update(end_s=500.0), "beyond audio duration"),
    (lambda d: d["mel_spectrogram"]["db"].pop(), "rows x"),
    (lambda d: d["waveform_peaks"]["max"].pop(), "same length"),
    (lambda d: d["pitch"]["values"].pop(), "values and times_s"),
    (lambda d: d["audio_quality"].update(call_score=1.4), "call_score"),
    (lambda d: d.update(feature_maps_status="ok"), "exactly when feature_maps_status is ok"),
    (lambda d: d.update(feature_maps=[_feature_window()]), "exactly when feature_maps_status is ok"),
])
def test_analysis_semantics(mutate, fragment):
    assert any(fragment in e for e in errs_after(AnalysisArtifact, "call_MOCK_001.analysis.json", mutate))


def test_analysis_feature_map_values_and_shape_checked():
    w = _feature_window()
    w["layers"][0]["values"][0][0] = 1.5
    w["layers"][0]["shape"] = [3, 3]
    d = fx("call_MOCK_001.analysis.json")
    d.update(feature_maps=[w], feature_maps_status="ok")
    errs = AnalysisArtifact.validate(d)
    assert any("normalised to [-1, 1]" in e for e in errs) and any("shape must match" in e for e in errs)


def test_analysis_minimal_is_valid():
    assert AnalysisArtifact.validate({"call_id": "c", "duration_s": 10.0, "sample_rate": 16000}) == []


@pytest.mark.parametrize("row, fragment", [
    ({"call_id": "c", "status": "done"}, "needs decision and risk_score"),
    ({"call_id": "c", "status": "error", "decision": "no_alert", "risk_score": 0.1, "n_stage_errors": 1},
     "other than no_alert"),
    ({"call_id": "c", "status": "sleeping"}, "status"),
    ({"call_id": "c", "status": "done", "decision": "review", "risk_score": 0.5, "n_stage_errors": 2},
     "requires status error"),
    ({"call_id": "c", "status": "queued", "criteria": ["vibes"]}, "criteria item"),
])
def test_call_list_item_semantics(row, fragment):
    assert any(fragment in e for e in CallListItem.validate(row))


@pytest.mark.parametrize("ev, fragment", [
    ({"seq": 1, "event": "stage_failed", "call_id": "c", "ts": "t", "stage": "asr"}, "needs a message"),
    ({"seq": 1, "event": "stage_started", "call_id": "c", "ts": "t", "stage": "lunch"}, "stage"),
    ({"seq": 1, "event": "job_finished", "call_id": "c", "ts": "t"}, "decision"),
    ({"seq": 1, "event": "stage_started", "call_id": "c", "ts": "t", "stage": "asr", "decision": "alarm"},
     "only set on job_finished"),
])
def test_processing_event_semantics(ev, fragment):
    assert any(fragment in e for e in ProcessingEvent.validate(ev))


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d["overall"]["strict_alarm"].update(tp=99), "tp+fp+fn+tn must equal n"),
    (lambda d: d["overall"]["three_class"]["confusion"]["alarm"].update(alarm=0), "confusion must sum to n"),
    (lambda d: d["overall"]["escalation"]["recall"].update(ci_low=0.9, ci_high=0.1), "ci_low <= ci_high"),
    (lambda d: d["overall"]["escalation"]["recall"].update(ci_high=None), "both be set or both be null"),
    (lambda d: d["breakdowns"]["variant"].pop("noisy"), "add up to overall.n"),
    (lambda d: d["threshold_curves"][0]["points"].reverse(), "strictly increasing"),
    (lambda d: d["reliability"]["bins"].pop(0), "tile [0, 1]"),
    (lambda d: d["reliability"].update(bins=[
        {"lo": 0.0, "hi": -0.5, "n": 0, "mean_confidence": None, "accuracy": None},
        {"lo": -0.5, "hi": 1.0, "n": 0, "mean_confidence": None, "accuracy": None}]), "need 0 <= lo < hi <= 1"),
    (lambda d: d["ablations"][0].update(name="vibes_only"), "ablations[0].name"),
    (lambda d: d["latency"][0].update(p50_s=99.0), "p50_s <= p95_s"),
    (lambda d: d.update(split="train"), "split"),
])
def test_quality_report_semantics(mutate, fragment):
    assert any(fragment in e for e in errs_after(QualityReport, "quality_report.json", mutate))
