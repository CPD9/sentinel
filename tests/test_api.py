"""API contract tests in fixture mode (docs/API.md). Skipped when the API deps are not installed:
uv pip install -r services/api/requirements.txt"""
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ["SENTINEL_FIXTURES"] = "1"
os.environ["SENTINEL_REPLAY_SCALE"] = "0"   # replay events without waiting

from fastapi.testclient import TestClient  # noqa: E402

from pipeline import schemas  # noqa: E402
from services.api import settings  # noqa: E402
from services.api.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_settings():
    settings.reset()
    yield
    settings.reset()


def assert_error(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error", "detail"} and body["error"] == code


def sse_events(text):
    """Parse an SSE body into (id, event, data) tuples, ignoring comments."""
    out = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
        if lines:
            fields = dict(ln.split(": ", 1) for ln in lines)
            out.append((fields["id"], fields["event"], fields["data"]))
    return out


# ----------------------------------------------------------------- health + calls
def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_calls_list_and_filters():
    rows = client.get("/api/calls").json()
    assert [r["call_id"] for r in rows] == ["call_MOCK_001", "call_MOCK_002", "call_MOCK_003", "call_MOCK_004"]
    assert all(schemas.CallListItem.validate(r) == [] for r in rows)
    assert [r["call_id"] for r in client.get("/api/calls?decision=alarm").json()] == ["call_MOCK_001"]
    assert [r["call_id"] for r in client.get("/api/calls?status=processing").json()] == ["call_MOCK_003"]


def test_call_detail_done_processing_unknown():
    r = client.get("/api/calls/call_MOCK_001")
    assert r.status_code == 200 and schemas.validate_call_result(r.json()) == []
    r = client.get("/api/calls/call_MOCK_003")
    assert r.status_code == 202 and r.json()["status"] == "processing"
    r = client.get("/api/calls/call_MOCK_004")   # stage error -> real review, never no_alert
    assert r.status_code == 200 and r.json()["decision"] == "review" and r.json()["stage_errors"]
    assert_error(client.get("/api/calls/call_UNKNOWN"), 404, "not_found")
    assert_error(client.get("/api/calls/bad-id!"), 404, "not_found")


def test_side_documents():
    assert client.get("/api/calls/call_MOCK_001/transcript").status_code == 200
    assert client.get("/api/calls/call_MOCK_001/trace").status_code == 200
    assert client.get("/api/calls/call_MOCK_002/analysis").status_code == 200
    assert_error(client.get("/api/calls/call_MOCK_004/transcript"), 404, "not_available")
    assert_error(client.get("/api/calls/call_UNKNOWN/trace"), 404, "not_found")


def test_audio_snippets_upload_are_off_in_fixture_mode():
    assert_error(client.get("/api/calls/call_MOCK_001/audio"), 404, "not_available")
    assert_error(client.get("/api/calls/call_MOCK_001/snippets/clip_1.wav"), 404, "not_available")
    assert_error(client.get("/api/calls/call_MOCK_001/snippets/clip.mp3"), 404, "not_found")
    assert_error(client.get("/api/calls/call_MOCK_001/snippets/..clip.wav"), 404, "not_found")
    assert_error(client.post("/api/calls"), 409, "conflict")


def test_unknown_route_uses_error_body():
    assert_error(client.get("/api/nothing"), 404, "not_found")


# ----------------------------------------------------------------- events
def test_call_events_replay_and_close():
    r = client.get("/api/calls/call_MOCK_001/events")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    assert len(events) == 22 and events[0][0] == "call_MOCK_001:1" and events[-1][1] == "job_finished"


def test_call_events_resume_after_last_event_id():
    r = client.get("/api/calls/call_MOCK_001/events", headers={"Last-Event-ID": "call_MOCK_001:20"})
    assert [e[0] for e in sse_events(r.text)] == ["call_MOCK_001:21", "call_MOCK_001:22"]


def test_synthesized_events_for_stage_error_call():
    kinds = [e[1] for e in sse_events(client.get("/api/calls/call_MOCK_004/events").text)]
    assert kinds == ["job_queued", "stage_started", "stage_failed", "job_finished"]


# ----------------------------------------------------------------- settings
def test_thresholds_get_put_and_422():
    assert client.get("/api/settings/thresholds").json() == {"alarm": 0.7, "review": 0.4, "confidence_gate": 0.5}
    assert_error(client.put("/api/settings/thresholds", json={"alarm": 0.5, "review": 0.6, "confidence_gate": 0.5}),
                 422, "invalid")
    r = client.put("/api/settings/thresholds", json={"alarm": 0.85, "review": 0.4, "confidence_gate": 0.5})
    assert r.status_code == 202 and r.json()["rerun"]["stages"] == ["rules", "confidence", "decide"]
    assert client.get("/api/settings/thresholds").json()["alarm"] == 0.85


def test_keywords_and_rules_validation():
    assert_error(client.put("/api/settings/keywords", json={"fuzzy_threshold": 0.8, "families": {"weather": {}}}),
                 422, "invalid")
    kw = client.get("/api/settings/keywords").json()
    kw["families"]["access"]["terms"].append("TAN")
    assert client.put("/api/settings/keywords", json=kw).status_code == 202
    assert "TAN" in client.get("/api/settings/keywords").json()["families"]["access"]["terms"]
    assert_error(client.put("/api/settings/rules", json={"version": "x", "rules": [{"criterion": "nope", "enabled": True}]}),
                 422, "invalid")


def test_preview_shows_alarm_flipping_to_review_without_saving():
    r = client.post("/api/settings/preview", json={"thresholds": {"alarm": 0.95, "review": 0.4, "confidence_gate": 0.5}})
    body = r.json()
    assert r.status_code == 200
    assert body["decision_counts"]["before"]["alarm"] == 1 and body["decision_counts"]["after"]["alarm"] == 0
    assert body["changed"] == [{"call_id": "call_MOCK_001", "decision_before": "alarm", "decision_after": "review",
                                "risk_before": 0.91, "risk_after": 0.91}]
    assert body["keyword_hit_counts"]["access"]["Passwort"] > 0
    assert client.get("/api/settings/thresholds").json()["alarm"] == 0.7   # nothing saved


# ----------------------------------------------------------------- quality
def test_quality_list_and_detail():
    reports = client.get("/api/quality").json()
    assert isinstance(reports, list) and reports[0]["report_id"] == "quality_MOCK_test" and reports[0]["is_mock"]
    assert client.get("/api/quality/quality_MOCK_test").status_code == 200
    assert_error(client.get("/api/quality/nope"), 404, "not_found")
