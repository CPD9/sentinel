import json
import urllib.error

from pipeline import trigger as tg
from pipeline.schemas import Evidence, Finding


def alarm_findings():
    return [Finding("credential_sharing", 0.9, "x" * 5000, [Evidence(["S1"], "customer", "Mis Passwort", 95.4, 97.0)])]


def test_dry_run_default_writes_valid_payload(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIGGER_URL", raising=False)
    recs, errs = tg.send_triggers("call_001", "alarm", alarm_findings(), tmp_path, ui_base="https://ui.example")
    assert errs == [] and recs[0]["mode"] == "dry-run"
    p = json.loads((tmp_path / "call_001_0.json").read_text())["payload"]
    assert p["url"] == "https://ui.example/calls/call_001?t=95"
    assert len(p["title"]) <= 200 and len(p["description"]) <= 2000


def test_only_alarms_trigger(tmp_path):
    assert tg.send_triggers("c", "review", alarm_findings(), tmp_path) == ([], [])
    assert list(tmp_path.iterdir()) == []


def test_real_post_only_with_trigger_url(tmp_path, monkeypatch):
    sent = {}

    def fake_post(base, payload, timeout=10.0):
        sent.update(base=base, payload=payload)
        return {"status": 201, "body": {"id": 1}}
    monkeypatch.setattr(tg, "_post", fake_post)
    monkeypatch.delenv("TRIGGER_URL", raising=False)
    tg.send_triggers("c", "alarm", alarm_findings(), tmp_path)
    assert sent == {}
    monkeypatch.setenv("TRIGGER_URL", "http://localhost:8080")
    recs, errs = tg.send_triggers("c", "alarm", alarm_findings(), tmp_path)
    assert sent["base"] == "http://localhost:8080" and set(sent["payload"]) == {"url", "title", "description"}
    assert recs[0]["mode"] == "send" and errs == []


def test_http_error_is_stage_error_not_exception(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(tg, "_post", boom)
    monkeypatch.setenv("TRIGGER_URL", "http://localhost:1")
    recs, errs = tg.send_triggers("c", "alarm", alarm_findings(), tmp_path)
    assert [e.stage for e in errs] == ["trigger"] and "error" in recs[0]


def test_rerun_does_not_repost_accepted_trigger(tmp_path, monkeypatch):
    posts = []
    monkeypatch.setattr(tg, "_post", lambda base, payload, timeout=10.0: (posts.append(payload), {"status": 201, "body": {"id": 7}})[1])
    monkeypatch.setenv("TRIGGER_URL", "http://localhost:8080")
    for _ in range(3):
        recs, errs = tg.send_triggers("c", "alarm", alarm_findings(), tmp_path, ui_base="https://ui.example")
        assert errs == [] and recs[0]["response"]["body"] == {"id": 7}
    assert len(posts) == 1


def test_changed_payload_or_earlier_failure_posts_again(tmp_path, monkeypatch):
    posts, fail = [], [True]

    def post(base, payload, timeout=10.0):
        posts.append(payload)
        if fail[0]:
            raise urllib.error.URLError("down")
        return {"status": 201, "body": {}}
    monkeypatch.setattr(tg, "_post", post)
    monkeypatch.setenv("TRIGGER_URL", "http://localhost:8080")
    tg.send_triggers("c", "alarm", alarm_findings(), tmp_path)
    fail[0] = False
    tg.send_triggers("c", "alarm", alarm_findings(), tmp_path)           # earlier attempt failed -> retry
    tg.send_triggers("c", "alarm", alarm_findings(), tmp_path)           # accepted -> reused
    other = alarm_findings()
    other[0].reason = "a different reason"
    tg.send_triggers("c", "alarm", other, tmp_path)                      # content changed -> new trigger
    assert len(posts) == 3
