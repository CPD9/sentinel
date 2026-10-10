"""Milestone 3: pipeline/asr.py with a MOCK faster-whisper model (no download, no GPU) and the
analysis-artifact merge helpers in pipeline/audio_analysis.py."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")
pytest.importorskip("librosa")

from pipeline import asr  # noqa: E402
from pipeline import audio_analysis as aa  # noqa: E402
from pipeline.schemas import AnalysisArtifact, StageError, Transcript  # noqa: E402

SR = 16000


def seg(start, end, text, lp=-0.3, ns=0.01, words=()):
    return SimpleNamespace(start=start, end=end, text=text, avg_logprob=lp, no_speech_prob=ns,
                           words=[SimpleNamespace(start=a, end=b, word=w, probability=0.9) for a, b, w in words])


class MockWhisper:
    """MOCK: stands in for faster_whisper.WhisperModel."""
    calls = 0

    def __init__(self, segments):
        self.segments = segments

    def transcribe(self, audio, **kw):
        MockWhisper.calls += 1
        assert kw == asr.DECODE
        return iter(self.segments), SimpleNamespace(language="de", language_probability=0.97)


@pytest.fixture
def env(tmp_path, monkeypatch):
    wav = tmp_path / "call_t01.wav"
    sf.write(wav, np.zeros(SR * 10, dtype=np.float32), SR, subtype="PCM_16")
    model_dir = tmp_path / "mock-model-ct2"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")
    segments = [seg(0.0, 2.5, " Grüezi, Rosenau Bank. ", words=[(0.0, 0.6, "Grüezi")]),
                seg(2.5, 2.5, "zero length"),
                seg(3.0, 4.0, "   "),
                seg(4.0, 10.4, "Ich bruch mini PIN.", lp=0.2, ns=1.3)]   # overshoots duration; bad probs
    MockWhisper.calls = 0
    monkeypatch.setattr(asr, "load_model", lambda *a: MockWhisper(segments))
    monkeypatch.setattr(asr, "default_device", lambda: ("cpu", "int8"))
    dirs = {"cache_dir": tmp_path / "cache", "transcripts_dir": tmp_path / "tr", "analysis_dir": tmp_path / "an"}
    return SimpleNamespace(wav=wav, model=str(model_dir), dirs=dirs, tmp=tmp_path)


def test_transcribe_converts_clamps_and_validates(env):
    t = asr.transcribe(env.wav, "call_t01", model_spec=env.model, **env.dirs)
    assert [s.id for s in t.segments] == ["S0001", "S0002"]
    assert t.segments[0].text == "Grüezi, Rosenau Bank." and t.segments[0].speaker == "unknown"
    last = t.segments[-1]
    assert last.end_s == 10.0 and last.avg_logprob == 0.0 and last.no_speech_prob == 1.0
    assert sum("dropped segment" in n for n in t.notes) == 2
    assert t.asr_model.startswith("mock-model-ct2@sha-")
    assert Transcript.validate(json.loads((env.dirs["transcripts_dir"] / "call_t01.json").read_text())) == []

    d = json.loads((env.dirs["analysis_dir"] / "call_t01" / "analysis.json").read_text())
    assert AnalysisArtifact.validate(d) == []
    assert d["duration_s"] == 10.0 and d["sample_rate"] == SR and d["versions"]["asr"] == t.asr_model
    pts = d["asr_confidence"]["segments"]
    assert [p["segment_id"] for p in pts] == ["S0001", "S0002"] and pts[0]["avg_logprob"] == -0.3


def test_cache_hit_and_force(env):
    asr.transcribe(env.wav, "call_t01", model_spec=env.model, **env.dirs)
    asr.transcribe(env.wav, "call_t01", model_spec=env.model, **env.dirs)
    assert MockWhisper.calls == 1
    asr.transcribe(env.wav, "call_t01", model_spec=env.model, force=True, **env.dirs)
    assert MockWhisper.calls == 2
    cached = list(env.dirs["cache_dir"].glob("*.json"))
    assert len(cached) == 1 and json.loads(cached[0].read_text())["raw"]["segments"][0]["words"]


def test_cache_key_changes_with_model_and_decode():
    k = asr.cache_key("a" * 64, "m@1")
    assert k != asr.cache_key("a" * 64, "m@2")
    assert k != asr.cache_key("a" * 64, "m@1", {**asr.DECODE, "beam_size": 1})


def test_merge_keeps_cpu_analysis_blocks(env):
    art = aa.analyze_call(env.wav, "call_t01")
    aa.save_analysis(art, env.dirs["analysis_dir"])
    asr.transcribe(env.wav, "call_t01", model_spec=env.model, **env.dirs)
    d = json.loads((env.dirs["analysis_dir"] / "call_t01" / "analysis.json").read_text())
    assert d["waveform_peaks"] and d["asr_confidence"] and d["versions"]["analysis"] == aa.ANALYSIS_VERSION


def test_cpu_reanalysis_keeps_asr_block(env, monkeypatch):
    asr.transcribe(env.wav, "call_t01", model_spec=env.model, **env.dirs)
    an = env.dirs["analysis_dir"]
    monkeypatch.setattr(aa, "_inference_index",
                        lambda: {"call_t01": {"audio_path": str(env.wav)}})
    monkeypatch.setattr(aa, "SPLITS_FILE", env.tmp / "splits.json")
    (env.tmp / "splits.json").write_text(json.dumps({"splits": {"test": {"call_ids": []}}}))
    rows = aa.run(call_ids=["call_t01"], out_dir=an, png=False)
    assert not rows[0].get("skipped")                 # an ASR-only artifact is not "already analysed"
    d = json.loads((an / "call_t01" / "analysis.json").read_text())
    assert d["asr_confidence"] and d["waveform_peaks"] and d["versions"]["asr"]
    assert aa.run(call_ids=["call_t01"], out_dir=an, png=False)[0]["skipped"]


def test_load_or_init_rejects_other_audio(tmp_path):
    aa.save_analysis(AnalysisArtifact(call_id="c", duration_s=10.0, sample_rate=SR), tmp_path)
    assert aa.load_or_init_analysis("c", 10.0, SR, tmp_path).duration_s == 10.0
    assert aa.load_or_init_analysis("new", 3.0, SR, tmp_path).asr_confidence is None
    with pytest.raises(ValueError):
        aa.load_or_init_analysis("c", 20.0, SR, tmp_path)


def test_save_analysis_rejects_invalid(tmp_path):
    with pytest.raises(ValueError):
        aa.save_analysis(AnalysisArtifact(call_id="c", duration_s=-1.0, sample_rate=SR), tmp_path)
    assert not (tmp_path / "c" / "analysis.json").exists()


def test_failure_is_a_stage_error_not_empty_transcript(env, monkeypatch):
    monkeypatch.setattr(asr, "load_model", lambda *a: MockWhisper([seg(0, 1, "  ")]))
    t, errors = asr.run_stage(env.wav, "call_t01", model_spec=env.model, **env.dirs)
    assert t is None and errors[0].stage == "asr" and "no usable segments" in errors[0].message
    t, errors = asr.run_stage(env.tmp / "missing.wav", "call_x", model_spec=env.model, **env.dirs)
    assert t is None and isinstance(errors[0], StageError) and "audio not found" in errors[0].message


def test_missing_model_path(monkeypatch):
    monkeypatch.delenv("ASR_MODEL_PATH", raising=False)
    monkeypatch.setattr(asr, "load_env", lambda: None)
    with pytest.raises(asr.AsrError):
        asr.resolve_model(None)
