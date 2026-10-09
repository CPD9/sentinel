"""Milestone 2: output contract in pipeline/schemas.py."""
import pytest

from pipeline.schemas import CallResult, RunResult, SchemaError, validate_call_result


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
