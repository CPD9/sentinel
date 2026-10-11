"""API contract tests in real mode (SENTINEL_RUN_DIR): the same app served from a pipeline run on disk.

The run is built in a temporary folder from copies of the MOCK fixtures, renamed to neutral ids, in the
layout process_call writes (docs/API.md "Files"). No real data is involved. Skipped without the API deps."""
import json
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ.setdefault("SENTINEL_FIXTURES", "1")   # the app module needs a store at import; each test swaps it
os.environ["SENTINEL_REPLAY_SCALE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from pipeline import schemas  # noqa: E402
from services.api import deps, feedback, settings  # noqa: E402
from services.api.main import app  # noqa: E402
from services.api.store import ArtifactStore, FixtureStore  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"
client = TestClient(app)
WAV = b"RIFF" + bytes(range(256)) * 4          # not a real wav; the API serves bytes as they are


def _copy_doc(src: str, dest: Path, old: str, new: str, edit=None) -> None:
    doc = json.loads((FIX / src).read_text(encoding="utf-8").replace(old, new))
    if edit:
        edit(doc)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def run(tmp_path):
    """A run with call_r01 (alarm, all documents, audio + one snippet) and call_r02 (no_alert, no analysis)."""
    out, art = tmp_path / "out", tmp_path / "artifacts"
    for old, new, analysis in (("call_MOCK_001", "call_r01", True), ("call_MOCK_002", "call_r02", False)):
        _copy_doc(f"{old}.result.json", out / "results" / f"{new}.json", old, new)
        _copy_doc(f"{old}.transcript.json", art / "transcripts" / f"{new}.json", old, new)
        # the run used other thresholds than the MOCK default: the settings must start from these
        _copy_doc(f"{old}.trace.json", art / "traces" / f"{new}.json", old, new,
                  edit=lambda d: d["thresholds"].update(alarm=0.8, review=0.45))
        if analysis:
            _copy_doc(f"{old}.analysis.json", art / "analysis" / new / "analysis.json", old, new)
    (art / "audio").mkdir(parents=True)
    (art / "audio" / "call_r01.wav").write_bytes(WAV)
    (out / "snippets" / "call_r01").mkdir(parents=True)
    (out / "snippets" / "call_r01" / "f0_e0.wav").write_bytes(WAV[:100])
    (out / "results" / ".call_r03.json.abc.tmp").write_text("{", encoding="utf-8")    # half-written: ignored
    # a label file must never be read: if any code opened it, the JSON error would fail the test
    (art / "manifests").mkdir(parents=True)
    (art / "manifests" / "evaluation.json").write_text("not json", encoding="utf-8")

    deps.store.use(ArtifactStore(tmp_path))
    settings.reset()
    feedback.reset()
    yield tmp_path
    deps.store.use(FixtureStore())
    settings.reset()
    feedback.reset()


def assert_error(r, status, code):
    assert r.status_code == status, r.text
    assert r.json()["error"] == code


def test_health_reports_real_mode(run):
    assert client.get("/api/health").json()["versions"]["mode"] == "artifacts"


def test_call_list_is_built_from_the_results(run):
    rows = client.get("/api/calls").json()
    assert [r["call_id"] for r in rows] == ["call_r01", "call_r02"]          # the .tmp file is skipped
    assert all(schemas.CallListItem.validate(r) == [] for r in rows)
    r1, r2 = rows
    assert r1["decision"] == "alarm" and r1["status"] == "done" and r1["is_mock"] is False
    assert r1["criteria"][0] == "credential_sharing"                            # risk-descending
    assert r1["duration_s"] is not None and r1["updated_at"].endswith("Z")
    assert r2["decision"] == "no_alert"
    assert [r["call_id"] for r in client.get("/api/calls?decision=alarm").json()] == ["call_r01"]


def test_documents_and_missing_ones(run):
    assert client.get("/api/calls/call_r01").json()["call_id"] == "call_r01"
    for kind in ("transcript", "trace", "analysis"):
        assert client.get(f"/api/calls/call_r01/{kind}").status_code == 200
    assert_error(client.get("/api/calls/call_r02/analysis"), 404, "not_available")
    assert_error(client.get("/api/calls/call_MOCK_001"), 404, "not_found")      # fixtures are not mixed in


def test_audio_and_snippets_with_range(run):
    r = client.get("/api/calls/call_r01/audio")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == WAV
    r = client.get("/api/calls/call_r01/audio", headers={"Range": "bytes=4-13"})
    assert r.status_code == 206 and r.content == WAV[4:14] and r.headers["content-range"] == f"bytes 4-13/{len(WAV)}"
    r = client.get("/api/calls/call_r01/audio", headers={"Range": "bytes=-10"})
    assert r.status_code == 206 and r.content == WAV[-10:]
    assert client.get("/api/calls/call_r01/audio", headers={"Range": "bytes=99999-"}).status_code == 416
    assert client.get("/api/calls/call_r01/snippets/f0_e0.wav").content == WAV[:100]
    assert_error(client.get("/api/calls/call_r01/snippets/f9_e9.wav"), 404, "not_available")
    assert_error(client.get("/api/calls/call_r01/snippets/..wav"), 404, "not_found")
    assert_error(client.get("/api/calls/call_r02/audio"), 404, "not_available")


def test_feedback_is_appended_to_the_run_and_survives_a_reset(run):
    r = client.post("/api/feedback", json={"call_id": "call_r01", "verdict": "correct", "note": "clear"})
    assert r.status_code == 201 and r.json()["is_mock"] is False
    client.post("/api/feedback", json={"call_id": "call_r01", "verdict": "false_alarm"})    # change of mind
    lines = (run / "out" / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                                                    # append-only log
    feedback.reset()                                                          # e.g. an API restart
    rows = client.get("/api/feedback").json()
    assert [(e["call_id"], e["verdict"]) for e in rows] == [("call_r01", "false_alarm")]
    assert_error(client.post("/api/feedback", json={"call_id": "call_r02", "verdict": "false_alarm"}), 422, "invalid")


def test_settings_start_from_the_run(run):
    th = client.get("/api/settings/thresholds").json()
    assert th["alarm"] == 0.8 and th["review"] == 0.45


def test_run_dir_without_results_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("SENTINEL_FIXTURES", raising=False)
    monkeypatch.setenv("SENTINEL_RUN_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="no out/results"):
        deps.make_store()


def test_snippet_name_cannot_leave_the_call_folder(run):
    (run / "out" / "snippets" / "call_r02").mkdir(parents=True)
    shutil.copy(run / "out" / "snippets" / "call_r01" / "f0_e0.wav", run / "out" / "snippets" / "call_r02" / "x.wav")
    assert deps.store.snippet_path("call_r01", "x.wav") is None


def test_a_run_shared_as_out_star_is_found(run):
    (run / "out").rename(run / "out_jules")                     # e.g. a run handed over as out_jules/
    assert ArtifactStore(run).out.name == "out_jules"
    deps.store.use(ArtifactStore(run))
    assert [r["call_id"] for r in client.get("/api/calls").json()] == ["call_r01", "call_r02"]


def test_reference_runs_never_mix_in_asr_documents(run):
    res = run / "out" / "results" / "call_r01.json"
    doc = json.loads(res.read_text(encoding="utf-8"))
    doc["versions"]["asr"] = "reference-transcript"           # this result ran on reference transcripts
    res.write_text(json.dumps(doc), encoding="utf-8")
    # only the ASR-run documents exist: they belong to another run, so they are not served
    assert_error(client.get("/api/calls/call_r01/trace"), 404, "not_available")
    ref = run / "artifacts" / "traces_reference"
    ref.mkdir()
    shutil.copy(run / "artifacts" / "traces" / "call_r01.json", ref / "call_r01.json")
    assert client.get("/api/calls/call_r01/trace").status_code == 200
