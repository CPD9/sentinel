"""Officer feedback log and audit log: validation, latest-wins, torn-line safety, concurrent atomic appends."""
import json
import multiprocessing

import pytest

from pipeline.feedback import (append_audit, append_feedback, latest_feedback, make_entry, now_ts, read_audit,
                               read_feedback_log)
from pipeline.schemas import AuditEntry, FeedbackEntry, SchemaError, verdict_allowed


def test_make_entry_accepts_each_valid_combination():
    for verdict, decision in [("false_alarm", "alarm"), ("false_alarm", "review"), ("missed", "no_alert"), ("missed", "review"),
                              ("correct", "alarm"), ("correct", "review"), ("correct", "no_alert")]:
        e = make_entry("call_001", verdict, decision, note="  ok  ", config_version="rules-v1+abc")
        assert (e.verdict, e.decision_at_feedback, e.note) == (verdict, decision, "ok")
        assert FeedbackEntry.validate(e.to_dict()) == []


@pytest.mark.parametrize("verdict,decision", [("false_alarm", "no_alert"), ("missed", "alarm"), ("maybe", "alarm"), ("correct", "flagged")])
def test_make_entry_rejects_impossible_combinations(verdict, decision):
    with pytest.raises(SchemaError):
        make_entry("call_001", verdict, decision)


@pytest.mark.parametrize("call_id", ["", "../etc/passwd", "call 1", "Stufe3_x.wav", "a/b"])
def test_make_entry_rejects_unsafe_call_ids(call_id):
    with pytest.raises(SchemaError):
        make_entry(call_id, "correct", "alarm")


def test_note_length_is_capped_and_empty_note_becomes_none():
    with pytest.raises(SchemaError):
        make_entry("call_001", "correct", "alarm", note="x" * 2001)
    assert make_entry("call_001", "correct", "alarm", note="   ").note is None


def test_verdict_allowed_matches_the_api_rule():
    assert not verdict_allowed("false_alarm", "no_alert") and not verdict_allowed("missed", "alarm")
    assert verdict_allowed("correct", "no_alert") and verdict_allowed("false_alarm", "review") and verdict_allowed("missed", "review")


def test_append_read_roundtrip_and_latest_verdict_wins(tmp_path):
    path = tmp_path / "out" / "feedback.jsonl"                  # parent directory is created on demand
    assert latest_feedback(path) == {} and read_feedback_log(path) == ([], [])
    append_feedback(make_entry("call_001", "false_alarm", "alarm", note="Kunde hat nur gefragt, grüezi öppis für Überweisig", ts="2026-10-10T10:00:00Z"), path)
    append_feedback(make_entry("call_002", "correct", "review", ts="2026-10-10T10:01:00Z"), path)
    append_feedback(make_entry("call_001", "correct", "alarm", ts="2026-10-10T10:02:00Z"), path)
    log, problems = read_feedback_log(path)
    assert problems == [] and [e.call_id for e in log] == ["call_001", "call_002", "call_001"]
    latest = latest_feedback(path)
    assert {c: e.verdict for c, e in latest.items()} == {"call_001": "correct", "call_002": "correct"}
    assert "Überweisig" in path.read_text(encoding="utf-8")       # not escaped to Ü: stays readable in the file


def test_append_rejects_an_invalid_entry_and_writes_nothing(tmp_path):
    path = tmp_path / "f.jsonl"
    bad = FeedbackEntry("call_001", "false_alarm", now_ts(), "no_alert")
    with pytest.raises(SchemaError):
        append_feedback(bad, path)
    assert not path.exists()


def test_corrupt_and_blank_lines_are_reported_not_fatal(tmp_path):
    path = tmp_path / "f.jsonl"
    append_feedback(make_entry("call_001", "correct", "alarm"), path)
    with open(path, "a", encoding="utf-8") as f:
        f.write("{not json\n\n" + json.dumps({"call_id": "call_9", "verdict": "false_alarm", "ts": "t", "decision_at_feedback": "no_alert"}) + "\n")
    append_feedback(make_entry("call_002", "missed", "no_alert"), path)
    log, problems = read_feedback_log(path)
    assert [e.call_id for e in log] == ["call_001", "call_002"]
    assert len(problems) == 2 and problems[0].startswith("f.jsonl:2:") and "makes no sense" in problems[1]


def _writer(args):
    path, worker, n = args
    for i in range(n):
        append_feedback(make_entry(f"call_{worker:02d}_{i:03d}", "correct", "alarm", note=("Überweisig " * 150)[:1900]), path)


def test_concurrent_appends_never_tear_a_line(tmp_path):
    path = tmp_path / "f.jsonl"
    with multiprocessing.get_context("fork").Pool(8) as pool:
        pool.map(_writer, [(path, w, 25) for w in range(8)])
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    log, problems = read_feedback_log(path)
    assert problems == [] and len(raw_lines) == 200 == len(log)
    assert len({e.call_id for e in log}) == 200


def test_audit_roundtrip_and_validation(tmp_path):
    path = tmp_path / "audit.jsonl"
    e = AuditEntry(now_ts(), "apply_suggestion", {"thresholds": {"alarm": 0.8}}, "rules-v1+aaa", "rules-v1+bbb", "abc123", "weil Fehlalarme", 3)
    append_audit(e, path)
    items, problems = read_audit(path)
    assert problems == [] and items == [e]
    with pytest.raises(SchemaError):
        append_audit(AuditEntry(now_ts(), "delete_everything", {}, "a", "b"), path)
    assert len(read_audit(path)[0]) == 1
