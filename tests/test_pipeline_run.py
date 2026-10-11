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
    from pipeline import runner
    monkeypatch.setattr(runner, "_decision_source", lambda: "rules")     # judge-path tests switch it on themselves
    monkeypatch.setattr(stages, "run_judge", lambda t, *a: pytest.fail("judge must not run in rules mode"))
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


def test_provider_provenance_survives_a_failed_remote_extraction(env, monkeypatch):
    from pipeline.llm import ProviderSpec
    spec = ProviderSpec(name="openrouter", base_url="https://openrouter.ai/api/v1", key_env="K", self_hosted=False,
                        allowed_models=("a/b",))
    fake_extract(monkeypatch, [], boom=TimeoutError("read timed out"))
    # the chosen client is known before extraction starts, even if the extractor never records its own versions
    monkeypatch.setattr("pipeline.llm.from_env", lambda: types.SimpleNamespace(probe=lambda: {}, spec=spec))
    r = run(env)
    assert r["decision"] == "review" and r["stage_errors"][0]["stage"] == "extract"
    assert r["versions"]["provider"] == "openrouter" and r["versions"]["self_hosted"] is False
    trace = json.loads((env.art / "traces" / "call_t1.json").read_text())
    assert trace["versions"]["provider"] == "openrouter" and trace["versions"]["self_hosted"] is False


def test_stale_extractor_versions_do_not_override_the_selected_client(env, monkeypatch):
    from pipeline.llm import ProviderSpec
    spec = ProviderSpec(name="openrouter", base_url="https://openrouter.ai/api/v1", key_env="K", self_hosted=False,
                        allowed_models=("a/b",))
    fake_extract(monkeypatch, [], boom=TimeoutError("read timed out"))
    sys.modules["pipeline.extract"].VERSIONS = {"llm": "old@1", "prompt": "p1", "provider": "apertus_aws",
                                                "self_hosted": True}          # left over from an earlier call
    monkeypatch.setattr("pipeline.llm.from_env", lambda: types.SimpleNamespace(probe=lambda: {}, spec=spec))
    r = run(env)
    assert r["versions"]["provider"] == "openrouter" and r["versions"]["self_hosted"] is False


def test_refusal_before_any_client_leaves_provenance_unset(env, monkeypatch):
    from pipeline.llm import ProviderNotPermitted
    fake_extract(monkeypatch, [])

    def refuse():
        raise ProviderNotPermitted("remote provider 'openrouter' is not permitted")
    monkeypatch.setattr("pipeline.llm.from_env", refuse)
    r = run(env)
    assert r["decision"] == "review" and "not permitted" in r["stage_errors"][0]["message"]
    assert "provider" not in r["versions"]                       # nothing was sent anywhere


def test_missing_extract_module_is_review_never_silent(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "pipeline.extract", None)       # import fails; also keeps the test off any live endpoint
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
    fake_extract(monkeypatch, [Fact("F1", "customer", "disclose", "credentials", ["S3"], "Mis Passwort isch Sunneblueme", recipient_third_party=True)])
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
    fake_extract(monkeypatch, [Fact("F1", "customer", "disclose", "credentials", ["S3"], "Mis Passwort isch Sunneblueme", recipient_third_party=True)])
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
    fake_extract(monkeypatch, [Fact("F1", "customer", "disclose", "credentials", ["S3"], "Mis Passwort isch Sunneblueme", recipient_third_party=True)])
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


def _fail_writes(monkeypatch, needle):
    import pipeline.runner as rn
    real = rn.write_json_atomic

    def flaky(path, obj, *a, **k):
        if needle in str(path) and not getattr(flaky, "armed_off", False):
            raise OSError("disk full")
        return real(path, obj, *a, **k)
    monkeypatch.setattr(rn, "write_json_atomic", flaky)


def test_failed_result_write_is_review_not_healthy_no_alert(env, monkeypatch):
    _fail_writes(monkeypatch, "/results/")
    events = []
    r = run(env, no_llm=True, on_event=events.append)
    assert r["decision"] == "review" and "results" in {e["stage"] for e in r["stage_errors"]}
    assert "Decision no_alert" not in r["narrative"] and validate_call_result(r) == []
    assert events[-1]["event"] == "job_finished" and events[-1]["decision"] == "review"
    assert not (env.out / "results").exists() or not list((env.out / "results").glob("*"))      # no half-written file
    trace = json.loads((env.art / "traces" / "call_t1.json").read_text())
    assert trace["decision"] == "review" and trace["decision_path"] == "stage_error"


def test_failed_trace_write_regenerates_narrative(env, monkeypatch):
    _fail_writes(monkeypatch, "/traces")
    r = run(env, no_llm=True)
    assert r["decision"] == "review" and "trace" in {e["stage"] for e in r["stage_errors"]}
    assert "Decision no_alert" not in r["narrative"] and "Decision review" in r["narrative"]
    assert json.loads((env.out / "results" / "call_t1.json").read_text())["decision"] == "review"


def test_snippet_failure_keeps_alarm_and_its_narrative(env, monkeypatch):
    fake_extract(monkeypatch, [Fact("F1", "customer", "disclose", "credentials", ["S3"], "Mis Passwort isch Sunneblueme", recipient_third_party=True)])
    env.wav.write_bytes(b"corrupt")
    r = run(env)
    assert r["decision"] == "alarm" and "Decision alarm" in r["narrative"]


def test_audio_analysis_dependency_is_optional(tmp_path, monkeypatch):
    """numpy missing (only requirements-dev.txt installed): import works and the call still completes."""
    import subprocess
    code = ("import sys; sys.modules['numpy'] = None\n"
            "import pipeline.stages, pipeline.runner, run\n"
            "from pipeline import stages\n"
            "art, errs, cached = stages.run_analysis('x.wav', 'call_t1', __import__('pathlib').Path('.'))\n"
            "assert art is None and errs and errs[0].stage == 'analysis', errs\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stderr[-800:]


def test_call_completes_without_analysis_dependency(env, monkeypatch):
    monkeypatch.undo()           # drop the env stubs, keep tmp paths
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.delitem(sys.modules, "pipeline.audio_analysis", raising=False)
    monkeypatch.setattr(stages, "run_asr", lambda audio, cid, **k: (asr_transcript(cid), []))
    r = run(env, no_llm=True)
    assert r["stage_errors"] == [] and r["decision"] in ("no_alert", "review")


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


def test_post_decision_escalation_rewrites_trace(env, monkeypatch):
    import pipeline.narrate as nar
    monkeypatch.setattr(nar, "narrate", lambda *a: (_ for _ in ()).throw(RuntimeError("narrate broke")))
    r = run(env, no_llm=True)
    trace = json.loads((env.art / "traces" / "call_t1.json").read_text())
    assert r["decision"] == "review" and any(e["stage"] == "narrate" for e in r["stage_errors"])
    assert trace["decision"] == r["decision"] == "review" and trace["decision_path"] == "stage_error"
    from pipeline.schemas import DecisionTrace
    assert DecisionTrace.validate(trace) == []


def fake_judge(monkeypatch, decision, cites, risk=0.9, boom=None):
    from pipeline import judge, runner
    from pipeline.validate import validate_facts
    monkeypatch.setattr(runner, "_decision_source", lambda: "direct_judge")

    def run_judge(t, *a):
        if boom:
            return None, [StageError("judge", str(boom))]
        facts = [Fact(f"j{i:03d}", "customer", "other", "other", [sid], q) for i, (sid, q) in enumerate(cites, 1)]
        return judge.JudgeResult(decision, "credential_sharing", risk, "reads out an active password",
                                 validate_facts(facts, t)), []
    monkeypatch.setattr(stages, "run_judge", run_judge)


def test_judge_alarm_with_validated_citation_decides_and_cuts_its_snippet(env, monkeypatch):
    fake_extract(monkeypatch, [])                       # facts -> rules alone would be no_alert
    fake_judge(monkeypatch, "alarm", [("S3", "Mis Passwort isch Sunneblueme")])
    r = run(env)
    assert r["decision"] == "alarm" and r["stage_errors"] == [] and validate_call_result(r) == []
    ev = r["findings"][0]["evidence"][0]
    assert ev["segment_ids"] == ["S3"] and ev["start_s"] == 20.0 and ev["snippet_path"].endswith(".wav")
    trace = json.loads((env.art / "traces" / "call_t1.json").read_text())
    assert trace["decision_path"] == "judge_alarm" and trace["rules"]               # rules stay as the why
    assert json.loads((env.out / "judge" / "call_t1.json").read_text())["decision"] == "alarm"


def test_judge_alarm_without_a_valid_citation_is_review_never_alarm(env, monkeypatch):
    fake_extract(monkeypatch, [])
    fake_judge(monkeypatch, "alarm", [("S3", "words that were never said in this call at all")])
    r = run(env)
    assert r["decision"] == "review"
    trace = json.loads((env.art / "traces" / "call_t1.json").read_text())
    assert trace["decision_path"] == "judge_review" and trace["why_not_flagged"] and trace["what_would_change"]


def test_judge_failure_is_review_with_stage_error(env, monkeypatch):
    fake_extract(monkeypatch, [])
    fake_judge(monkeypatch, "no_alert", [], boom="judge unreachable")
    r = run(env)
    assert r["decision"] == "review" and [e["stage"] for e in r["stage_errors"]] == ["judge"]
