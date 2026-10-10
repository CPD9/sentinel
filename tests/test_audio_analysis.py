"""Milestone 3a: pipeline/audio_analysis.py on synthetic audio (no case data needed) plus one real call."""
import json
import re
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("librosa")
pytest.importorskip("soundfile")
import soundfile as sf  # noqa: E402

from pipeline import audio_analysis as aa  # noqa: E402
from pipeline.schemas import AnalysisArtifact  # noqa: E402

SR = 16000
REPO = Path(__file__).resolve().parents[1]
REAL = REPO / "artifacts" / "audio" / "call_002.wav"
needs_data = pytest.mark.skipif(not REAL.exists(), reason="case audio not available")


def synth(path, noise=0.0, seconds=24.0, seed=0):
    """Voiced bursts (200 Hz + harmonics, 2 s on / 1 s off) over optional white noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    voice = sum(np.sin(2 * np.pi * 200 * k * t) / k for k in range(1, 6))
    gate = ((t % 3.0) < 2.0).astype(float)
    y = 0.3 * voice * gate / 2.0 + noise * rng.standard_normal(len(t)) + 1e-4 * rng.standard_normal(len(t))
    sf.write(path, y.astype(np.float32), SR, subtype="PCM_16")
    return path


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    return synth(tmp_path_factory.mktemp("a") / "clean.wav")


@pytest.fixture(scope="module")
def noisy(tmp_path_factory):
    return synth(tmp_path_factory.mktemp("a") / "noisy.wav", noise=0.05)


@pytest.fixture(scope="module")
def art(clean):
    return aa.analyze_call(clean, "call_t01")


def test_schema_valid_and_roundtrip(art):
    d = art.to_dict()
    assert AnalysisArtifact.validate(d) == []
    assert AnalysisArtifact.from_dict(json.loads(json.dumps(d))).call_id == "call_t01"


def test_empty_blocks_and_state(art):
    assert art.turns is None and art.asr_confidence is None and art.feature_maps is None
    assert art.feature_maps_status == "not_computed" and not art.is_mock
    assert {e.stage for e in art.stage_errors} == {"analysis.speech_rate"}


def test_shapes(art):
    m = art.mel_spectrogram
    assert len(m.db) == len(m.freqs_hz) == aa.MEL_BANDS and all(len(r) == len(m.times_s) for r in m.db)
    assert len(art.pitch.times_s) == len(art.pitch.values) == len(art.energy.values)
    assert art.pitch.times_s == art.energy.times_s
    assert abs(len(art.waveform_peaks.min) * aa.PEAK_BUCKET_S - art.duration_s) <= aa.PEAK_BUCKET_S


def test_ranges(art):
    w = art.waveform_peaks
    assert min(w.min) >= -1 and max(w.max) <= 1 and all(a <= b for a, b in zip(w.min, w.max))
    assert max(max(r) for r in art.mel_spectrogram.db) <= aa.DB_MAX and min(min(r) for r in art.mel_spectrogram.db) >= aa.DB_MIN
    q = art.audio_quality
    assert 0 <= q.call_score <= 1 and all(0 <= s.score <= 1 for s in q.segments)
    iv = art.speech_activity.intervals
    assert iv and all(a.end_s <= b.start_s for a, b in zip(iv, iv[1:])) and iv[-1].end_s <= art.duration_s
    f0 = [v for v in art.pitch.values if v is not None]
    assert f0 and all(aa.PITCH_FMIN <= v <= aa.PITCH_FMAX for v in f0)
    assert np.median(f0) == pytest.approx(200, rel=0.05)


def test_vad_finds_the_bursts(art):
    covered = sum(i.end_s - i.start_s for i in art.speech_activity.intervals)
    assert covered == pytest.approx(16.0, abs=1.5)   # 8 bursts x 2 s


def test_quality_drops_with_noise(clean, noisy):
    assert aa.analyze_call(noisy, "n").audio_quality.call_score < aa.analyze_call(clean, "c").audio_quality.call_score


def test_deterministic(clean):
    a = json.dumps(aa.analyze_call(clean, "x").to_dict())
    assert a == json.dumps(aa.analyze_call(clean, "x").to_dict())


def test_failure_isolation(clean, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(aa, "_mel", boom)
    art = aa.analyze_call(clean, "x")
    assert art.mel_spectrogram is None and art.waveform_peaks is not None
    assert any(e.stage == "analysis.mel_spectrogram" and "boom" in e.message for e in art.stage_errors)
    assert AnalysisArtifact.validate(art.to_dict()) == []


def test_silence_does_not_crash(tmp_path):
    p = tmp_path / "s.wav"
    sf.write(p, np.zeros(SR * 3, dtype=np.float32), SR)
    art = aa.analyze_call(p, "s")
    assert AnalysisArtifact.validate(art.to_dict()) == []


def test_write_and_png(art, clean, tmp_path):
    p = aa.write_analysis(art, tmp_path)
    assert p.read_text().endswith("\n") and p.parent.name == "call_t01"
    aa.render_png(art, clean, tmp_path / "x.png")
    assert (tmp_path / "x.png").stat().st_size > 5000


def test_pipeline_never_reads_labels():
    src = (REPO / "pipeline" / "audio_analysis.py").read_text()
    assert not re.search(r"evaluation\.json|original_filename|\"variant\"|'variant'|\"label\"", src)


def test_runtime_per_audio_minute(clean):
    t0 = time.perf_counter()
    aa.analyze_call(clean, "r")
    per_min = (time.perf_counter() - t0) / (24.0 / 60)
    print(f"runtime: {per_min:.1f} s per audio minute")
    assert per_min < 20


@needs_data
def test_real_call_valid_and_size():
    art = aa.analyze_call(REAL, "call_002")
    d = art.to_dict()
    assert AnalysisArtifact.validate(d) == []
    assert len(json.dumps(d)) < 400_000
    assert art.audio_quality and art.speech_activity.intervals
