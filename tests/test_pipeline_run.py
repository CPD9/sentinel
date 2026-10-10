"""process_call end to end with fake ASR / LLM. Nothing here touches the network, a GPU or data/."""
import json
import sys
import types
import wave

import pytest

from pipeline import process_call, stages
from pipeline.schemas import Fact, StageError, Transcript, TranscriptSegment, validate_call_result

TEXTS = [("advisor", "Grüezi, Bank Lindenhof."), ("customer", "Ich ha mis Passwort vergässe."),
         ("customer", "Mis Passwort isch Sunneblueme."), ("advisor", "Merci, uf Widerluege.")]


def make_wav(path, seconds=40, sr=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x01\x00" * int(seconds * sr))
    return path


def asr_transcript(call_id):
    segs = [TranscriptSegment(f"S{i + 1}", sp, t, 5.0 * i + 10, 5.0 * i + 13, -0.2, 0.01) for i, (sp, t) in enumerate(TEXTS)]
    return Transcript(call_id=call_id, mode="asr", segments=segs, asr_model="FAKE@1", duration_s=40.0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIGGER_URL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delitem(sys.modules, "pipeline.extract", raising=False)
    monkeypatch.setattr(stages, "run_analysis", lambda *a, **k: (None, [], False))
    monkeypatch.setattr(stages, "run_asr", lambda audio, cid, **k: (asr_transcript(cid), []))
    return types.SimpleNamespace(wav=make_wav(tmp_path / "a.wav"), art=tmp_path / "art", out=tmp_path / "out")


def run(env, **kw):
    return process_call(str(env.wav), "call_t1", artifacts_dir=env.art, out_dir=env.out, **kw)


def fake_extract(monkeypatch, facts, boom=None):
    mod = types.ModuleType("pipeline.extract")
    mod.VERSIONS = {"llm": "fake-llm@1", "prompt": "p1"}

    def extract_facts(t):
        if boom:
            raise boom
        return facts
    mod.extract_facts = extract_facts
    monkeypatch.setitem(sys.modules, "pipeline.extract", mod)
    monkeypatch.setattr("pipeline.llm.from_env", lambda: types.SimpleNamespace(probe=lambda: {}))


def test_provider_provenance_reaches_result_and_trace(env, monkeypatch):
    fake_extract(monkeypatch, [])
    sys.modules["pipeline.extract"].VERSIONS = {"llm": "m@1", "prompt": "p1", "provider": "openrouter",
                                                "self_hosted": False}
    r = run(env)
    assert r["versions"]["provider"] == "openrouter" and r["versions"]["self_hosted"] is False
    assert validate_call_result(r) == []
    trace = json.loads((env.art / "traces" / "call_t1.json").read_text())
    assert trace["versions"]["provider"] == "openrouter" and trace["versions"]["self_hosted"] is False


def test_missing_extract_module_is_review_never_silent(env):
    r = run(env)
    assert r["decision"] == "review" and [e["stage"] for e in r["stage_errors"]] == ["extract"]
    assert validate_call_result(r) == []


def test_unreachable_llm_is_review(env, monkeypatch):
    fake_extract(monkeypatch, [])
    from pipeline.llm import LLMError

    def dead():
        raise LLMError("cannot reach http://127.0.0.1:8000/v1")
    monkeypatch.setattr("pipeline.llm.from_env", dead)
    r = run(env)
    assert r["decision"] == "review" and r["stage_errors"][0]["stage"] == "extract"
    assert "cannot reach" in r["stage_errors"][0]["message"]


def test_asr_failure_is_review(env, monkeypatch):
    monkeypatch.setattr(stages, "run_asr", lambda *a, **k: (None, [StageError("asr", "RuntimeError: boom")]))
    r = run(env, no_llm=True)
    assert r["decision"] == "review" and r["stage_errors"][0]["stage"] == "asr"


def test_no_llm_is_not_a_stage_error_and_is_labelled(env):
    r = run(env, no_llm=True)
    assert r["stage_errors"] == [] and r["decision"] in ("no_alert", "review")
    assert r["versions"]["llm"].startswith("none")


def test_alarm_with_fake_llm_has_snippet_trigger_trace_and_result_file(env, monkeypatch):
    fake_extract(monkeypatch, [Fact("F1", "customer", "disclose", "credentials", ["S3"], "Mis Passwort isch Sunneblueme")])
    events = []
    r = run(env, on_event=events.append)
    assert r["decision"] == "alarm" and r["stage_errors"] == [] and validate_call_result(r) == []
    ev = r["findings"][0]["evidence"][0]
    assert ev["start_s"] == 20.0 and ev["snippet_path"] and ev["snippet_path"].endswith(".wav")
    assert (env.out / "triggers" / "call_t1_0.json").is_file()
    assert json.loads((env.out / "results" / "call_t1.json").read_text())["decision"] == "alarm"
    assert (env.art / "traces" / "call_t1.json").is_file()
    assert r["versions"]["llm"] == "fake-llm@1"
    names = [(e["event"], e.get("stage")) for e in events]
    assert names[0] == ("stage_started", "analysis") and names[-1][0] == "job_finished"
    assert events[-1]["decision"] == "alarm" and ("stage_finished", "extract") in names


def test_extractor_exception_is_review(env, monkeypatch):
    fake_extract(monkeypatch, [], boom=ValueError("bad json"))
    r = run(env)
    assert r["decision"] == "review" and "bad json" in r["stage_errors"][0]["message"]


def test_raising_callback_is_harmless_and_logged_once(env, monkeypatch, caplog):
    fake_extract(monkeypatch, [Fact("F1", "customer", "disclose", "credentials", ["S3"], "Mis Passwort isch Sunneblueme")])
    calls = []

    def bad(e):
        calls.append(e)
        raise RuntimeError("sse down")
    with caplog.at_level("WARNING", logger="sentinel.pipeline"):
        r = run(env, on_event=bad)
    expected = run(env)
    assert r["decision"] == expected["decision"] == "alarm" and len(calls) > 3
    assert sum("on_event callback raised" in m for m in caplog.messages) == 1


def test_unexpected_exception_becomes_review(env, monkeypatch):
    monkeypatch.setattr(stages, "build_findings", lambda *a: (_ for _ in ()).throw(KeyError("x")))
    r = run(env, no_llm=True)
    assert r["decision"] == "review" and r["stage_errors"][0]["stage"] == "pipeline"


def test_snippet_failure_does_not_change_decision(env, monkeypatch):
    fake_extract(monkeypatch, [Fact("F1", "customer", "disclose", "credentials", ["S3"], "Mis Passwort isch Sunneblueme")])
    env.wav.write_bytes(b"corrupt")
    r = run(env)
    assert r["decision"] == "alarm" and "snippets" in {e["stage"] for e in r["stage_errors"]}


def test_reference_mode_uses_scripts_without_timestamps(env, monkeypatch):
    turns = [{"segment_id": f"T{i + 1}", "speaker": sp, "text": t} for i, (sp, t) in enumerate(TEXTS)]
    monkeypatch.setattr(stages, "reference_transcript", lambda cid: turns)
    r = run(env, transcripts="reference", no_llm=True)
    assert validate_call_result(r) == [] and r["versions"]["asr"] == "reference-transcript"
    assert all(e["start_s"] is None for f in r["findings"] for e in f["evidence"])
    assert (env.art / "transcripts_reference" / "call_t1.json").is_file()
    assert not (env.art / "transcripts" / "call_t1.json").exists()      # never overwrites ASR transcripts


def test_reference_missing_is_review(env):
    r = run(env, transcripts="reference", no_llm=True)    # call_t1 is not in the manifest
    assert r["decision"] == "review" and r["stage_errors"][0]["stage"] == "asr"


def test_bad_call_id_rejected(env):
    with pytest.raises(ValueError):
        process_call(str(env.wav), "../x", out_dir=env.out)


def test_no_half_written_result_when_write_fails(env, monkeypatch):
    import pipeline.runner as rn
    real = rn.write_json_atomic

    def flaky(path, obj, *a, **k):
        if "results" in str(path):
            raise OSError("disk full")
        return real(path, obj, *a, **k)
    monkeypatch.setattr(rn, "write_json_atomic", flaky)
    r = run(env, no_llm=True)
    assert r["decision"] in ("no_alert", "review")
    assert not list((env.out / "results").glob("*")) if (env.out / "results").exists() else True


def test_pipeline_never_opens_labels(env, monkeypatch):
    opened = []
    real = open
    import builtins
    import pathlib

    def spy(f, *a, **k):
        opened.append(str(f))
        return real(f, *a, **k)
    monkeypatch.setattr(builtins, "open", spy)
    real_read = pathlib.Path.read_text
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, *a, **k: (opened.append(str(self)), real_read(self, *a, **k))[1])
    run(env, no_llm=True)
    assert not [o for o in opened if "evaluation" in o]
