"""Officer feedback, docs/API.md "What-if, feedback and suggestions": POST /feedback and GET /feedback.

The officer tells SENTINEL whether a decision was right (correct), wrong (false_alarm) or whether a call should
have been flagged (missed), or asks a person above them to look (escalate). A verdict never changes the decision;
false_alarm / missed / correct feed the suggestions, escalate does not. The latest verdict per call wins, so an
officer changes their mind by posting again.

Fixture mode: verdicts start from fixtures/feedback.json and new ones are kept in memory only (lost on restart),
so the demo works without writing to out/. Real mode (SENTINEL_RUN_DIR): every verdict is appended to the run's
out/feedback.jsonl via append_feedback, and GET reads the latest per call back from that file.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from pipeline.feedback import append_feedback, latest_feedback, make_entry
from pipeline.schemas import FeedbackEntry, SchemaError

from .deps import ApiError, known_call, store

router = APIRouter(prefix="/api/feedback")

# call_id -> latest FeedbackEntry dict (in memory in fixture mode). Insertion order = time order.
latest: dict[str, dict] = {}


def reset() -> None:
    """Back to the MOCK sample (also used by the tests). Real mode keeps nothing in memory."""
    latest.clear()
    if store.feedback_path is not None:
        return
    path = store.root / "feedback.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    for row in rows:
        if not FeedbackEntry.validate(row):
            latest[row["call_id"]] = row


reset()


@router.get("")
def list_feedback() -> list[dict]:
    """The latest verdict per call."""
    if store.feedback_path is not None:
        return [e.to_dict() for e in latest_feedback(store.feedback_path).values()]
    return list(latest.values())


@router.post("", status_code=201)
def post_feedback(body: Any = Body(...)) -> JSONResponse:
    if not isinstance(body, dict):
        raise ApiError(422, "invalid", "body must be an object {call_id, verdict, note?}")
    unknown = [k for k in body if k not in {"call_id", "verdict", "note"}]
    if unknown:
        raise ApiError(422, "invalid", [f"unknown key {k!r}" for k in unknown])
    call_id, verdict, note = body.get("call_id"), body.get("verdict"), body.get("note")
    if not isinstance(call_id, str):
        raise ApiError(422, "invalid", "call_id: required string")
    if not isinstance(verdict, str):
        raise ApiError(422, "invalid", "verdict: required string")
    if note is not None and not isinstance(note, str):
        raise ApiError(422, "invalid", "note: must be a string")

    row = known_call(call_id)                        # 404 for an unknown call
    decision = row.get("decision")
    if row.get("status") in ("queued", "processing") or not decision:
        raise ApiError(409, "conflict", f"Call {call_id!r} has no decision yet")
    result = store.get_result(call_id) or {}
    try:
        entry = make_entry(call_id, verdict, decision, note=note,
                           config_version=(result.get("versions") or {}).get("rules"), is_mock=store.is_mock)
    except SchemaError as e:
        raise ApiError(422, "invalid", e.errors)
    if store.feedback_path is not None:
        store.feedback_path.parent.mkdir(parents=True, exist_ok=True)
        append_feedback(entry, store.feedback_path)      # append-only log; the latest line per call wins
        return JSONResponse(entry.to_dict(), status_code=201)
    doc = entry.to_dict()
    latest.pop(call_id, None)                        # re-insert so the newest verdict is last
    latest[call_id] = doc
    return JSONResponse(doc, status_code=201)
