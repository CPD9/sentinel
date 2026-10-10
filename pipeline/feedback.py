"""Officer feedback and the config audit trail: two append-only JSON-lines files under out/.

  out/feedback.jsonl   one FeedbackEntry per line {call_id, verdict: false_alarm|missed|correct, note, ts, ...}
  out/audit.jsonl      one AuditEntry per line (config changes, e.g. an applied suggestion)

Appends are atomic: one `write` of a single newline-terminated line on an O_APPEND descriptor, under an exclusive
flock, then fsync. Concurrent writers (API worker threads, several processes) can interleave lines but never tear one.
The latest verdict per call_id wins; a corrupt line is reported and skipped, never fatal.

This is the only place feedback is read. It comes from the officer through the UI, never from ground-truth label files.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pipeline.schemas import AuditEntry, FeedbackEntry, SchemaError

REPO_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_FILE = REPO_ROOT / "out" / "feedback.jsonl"
AUDIT_FILE = REPO_ROOT / "out" / "audit.jsonl"


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_line(path: Path, obj: dict) -> None:
    line = (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            written = os.write(fd, line)
            if written != len(line):              # a short write would tear the line: refuse to leave it half-written
                raise OSError(f"short write to {path}: {written} of {len(line)} bytes")
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _read_lines(path: Path, schema) -> tuple[list, list[str]]:
    path = Path(path)
    if not path.exists():
        return [], []
    items, problems = [], []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            items.append(schema.from_dict(json.loads(raw)))
        except (json.JSONDecodeError, SchemaError) as e:
            problems.append(f"{path.name}:{n}: {e}")
    return items, problems


# --------------------------------------------------------------------------- feedback

def make_entry(call_id: str, verdict: str, decision_at_feedback: str, note: str | None = None,
               config_version: str | None = None, ts: str | None = None, is_mock: bool = False) -> FeedbackEntry:
    """Build and validate an entry; raises SchemaError (the API maps it to 422)."""
    e = FeedbackEntry(call_id, verdict, ts or now_ts(), decision_at_feedback, (note or "").strip() or None, config_version, is_mock)
    errs = FeedbackEntry.validate(e.to_dict())
    if errs:
        raise SchemaError(errs)
    return e


def append_feedback(entry: FeedbackEntry, path: Path = FEEDBACK_FILE) -> FeedbackEntry:
    errs = FeedbackEntry.validate(entry.to_dict())
    if errs:
        raise SchemaError(errs)
    _append_line(path, entry.to_dict())
    return entry


def read_feedback_log(path: Path = FEEDBACK_FILE) -> tuple[list[FeedbackEntry], list[str]]:
    """Every valid row in file order, plus one message per corrupt line."""
    return _read_lines(path, FeedbackEntry)


def latest_feedback(path: Path = FEEDBACK_FILE) -> dict[str, FeedbackEntry]:
    """call_id -> its latest verdict (file order = time order)."""
    items, _ = read_feedback_log(path)
    return {e.call_id: e for e in items}


# --------------------------------------------------------------------------- audit

def append_audit(entry: AuditEntry, path: Path = AUDIT_FILE) -> AuditEntry:
    errs = AuditEntry.validate(entry.to_dict())
    if errs:
        raise SchemaError(errs)
    _append_line(path, entry.to_dict())
    return entry


def read_audit(path: Path = AUDIT_FILE) -> tuple[list[AuditEntry], list[str]]:
    return _read_lines(path, AuditEntry)
