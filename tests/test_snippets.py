import shutil
import subprocess
import wave

import pytest

from pipeline import snippets as sn
from pipeline.schemas import Evidence, Finding

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def make_wav(path, seconds=30, sr=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x01\x00" * int(seconds * sr))
    return path


def finding(s, e):
    return Finding("credential_sharing", 0.9, "r", [Evidence(["S1"], "customer", "q", s, e)])


def test_window_clamps_to_audio():
    assert sn.snippet_window(3.0, 5.0, 30.0) == (0.0, 15.0)
    assert sn.snippet_window(25.0, 29.0, 30.0) == (15.0, 30.0)


@pytest.mark.parametrize("s,e", [(5, 5), (6, 5), (-1, 3), (40, 41)])
def test_window_rejects_bad_spans(s, e):
    with pytest.raises(sn.SnippetError):
        sn.snippet_window(s, e, 30.0)


def test_cut_is_playable_and_path_set(tmp_path):
    wav = make_wav(tmp_path / "a.wav")
    f = finding(12.0, 14.0)
    assert sn.cut_snippets(wav, "call_t", [f], 30.0, tmp_path / "snips") == []
    p = tmp_path / "snips" / "call_t" / f.evidence[0].snippet_path.split("/")[-1]
    assert abs(sn.probe_duration(p) - 22.0) < 0.25
    assert [x.name for x in p.parent.iterdir()] == [p.name]       # no temp files left


def test_edge_clamp_duration(tmp_path):
    wav = make_wav(tmp_path / "a.wav")
    f = finding(1.0, 2.0)
    assert sn.cut_snippets(wav, "call_t", [f], 30.0, tmp_path / "s") == []
    assert abs(sn.probe_duration(tmp_path / "s" / "call_t" / f.evidence[0].snippet_path.split("/")[-1]) - 12.0) < 0.25


def test_span_outside_audio_is_stage_error_without_path(tmp_path):
    wav = make_wav(tmp_path / "a.wav")
    f = finding(50.0, 52.0)
    errs = sn.cut_snippets(wav, "call_t", [f], 30.0, tmp_path / "s")
    assert [e.stage for e in errs] == ["snippets"] and f.evidence[0].snippet_path is None


def test_corrupt_audio_is_stage_error(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    errs = sn.cut_snippets(bad, "call_t", [finding(1.0, 2.0)], 30.0, tmp_path / "s")
    assert errs and errs[0].stage == "snippets"
    assert not (tmp_path / "s" / "call_t").exists() or not list((tmp_path / "s" / "call_t").iterdir())


def test_evidence_without_timestamps_is_skipped(tmp_path):
    f = Finding("other", 0.5, "r", [Evidence(["T1"], "advisor", "q")])
    assert sn.cut_snippets(make_wav(tmp_path / "a.wav"), "c", [f], 30.0, tmp_path / "s") == []
    assert f.evidence[0].snippet_path is None
