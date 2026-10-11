"""Live progress events over Server-Sent Events (docs/API.md "Live events").

SSE is a long-lived HTTP response in which the server keeps writing small text messages; the browser's
EventSource reads them as they arrive. One message per ProcessingEvent:

    id: call_MOCK_001:12
    event: stage_finished
    data: {"seq": 12, "event": "stage_finished", ...}

GET /api/calls/{id}/events  past events first (replay), then live ones; closes after job_finished.
GET /api/events             global stream for the Inbox, live only.

Fixture mode: per-call streams replay fixtures/<id>.events.json, paced by a fraction of the recorded
gaps so the Processing view visibly ticks. Calls without an event log get a short synthesized log
built from their inbox row and result. Nothing is live, so the global stream only sends heartbeats.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from pipeline import schemas

from .deps import known_call, log, store

router = APIRouter(prefix="/api")

HEARTBEAT_S = 15.0
# Fixture replay pacing: wait this fraction of each recorded gap between two events (0 = no waiting).
REPLAY_SCALE = float(os.environ.get("SENTINEL_REPLAY_SCALE", "0.1"))
MAX_REPLAY_GAP_S = 1.5
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


# --------------------------------------------------------------------------- wire format
def format_event(ev: dict) -> str:
    """One SSE message. The blank line at the end tells the browser the message is complete."""
    return f"id: {ev['call_id']}:{ev['seq']}\nevent: {ev['event']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"


def resume_after(last_event_id: str | None, call_id: str) -> int:
    """seq to resume after, from a Last-Event-ID header like 'call_MOCK_001:12' (0 = from the start)."""
    if not last_event_id:
        return 0
    cid, _, seq = last_event_id.rpartition(":")
    return int(seq) if cid == call_id and seq.isdigit() else 0


def _ts(ev: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(ev["ts"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return None


def replay_delay(prev: dict | None, ev: dict) -> float:
    if prev is None or REPLAY_SCALE <= 0:
        return 0.0
    a, b = _ts(prev), _ts(ev)
    gap = (b - a).total_seconds() if a and b else 0.0
    return min(max(gap, 0.0) * REPLAY_SCALE, MAX_REPLAY_GAP_S)


# --------------------------------------------------------------------------- event logs
def synth_events(call_id: str, row: dict, result: dict | None) -> list[dict]:
    """A minimal log for calls without a recorded one (all of them in real mode), consistent with their row and result."""
    ts = row.get("updated_at") or "1970-01-01T00:00:00Z"
    events: list[dict] = []

    def add(event: str, **kw) -> None:
        events.append({"seq": len(events) + 1, "event": event, "call_id": call_id, "ts": ts,
                       "stage": None, "elapsed_s": None, "cached": None, "message": None,
                       "decision": None, **kw})

    add("job_queued", message="[MOCK] synthesized event log" if store.is_mock else "synthesized from the stored result")
    add("stage_started", stage="asr")
    if result is None:          # queued / processing: the stream stays open after this
        return events
    for err in result.get("stage_errors", []):
        add("stage_failed", stage=err["stage"], message=err["message"])
    add("job_finished", decision=result["decision"])
    return events


def call_events(call_id: str, row: dict) -> list[dict]:
    events = store.get_events(call_id)
    if events is None:
        result = store.get_result(call_id) if row["status"] in ("done", "error") else None
        events = synth_events(call_id, row, result)
    for ev in events:
        errors = schemas.ProcessingEvent.validate(ev)
        if errors:  # log, never crash the stream (docs/API.md "Validation")
            log.error("event %s:%s failed validation: %s", call_id, ev.get("seq"), errors)
    return events


# --------------------------------------------------------------------------- streams
async def _heartbeats(request: Request) -> AsyncIterator[str]:
    """': ping' comment every 15 s until the client goes away (keeps proxies from closing the stream)."""
    waited = 0.0
    while not await request.is_disconnected():
        await asyncio.sleep(1.0)
        waited += 1.0
        if waited >= HEARTBEAT_S:
            waited = 0.0
            yield ": ping\n\n"


async def _call_stream(request: Request, events: list[dict], after_seq: int) -> AsyncIterator[str]:
    yield ": connected\n\n"
    prev = None
    for ev in events:
        if ev["seq"] <= after_seq:
            continue
        delay = replay_delay(prev, ev)
        if delay:
            await asyncio.sleep(delay)
        if await request.is_disconnected():
            return
        yield format_event(ev)
        prev = ev
    if events and events[-1]["event"] == "job_finished":
        return  # the stream closes after job_finished
    async for ping in _heartbeats(request):
        yield ping


@router.get("/calls/{call_id}/events")
def stream_call_events(call_id: str, request: Request,
                       last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    row = known_call(call_id)
    events = call_events(call_id, row)
    after = resume_after(last_event_id, call_id)
    return StreamingResponse(_call_stream(request, events, after),
                             media_type="text/event-stream", headers=SSE_HEADERS)


async def _global_stream(request: Request) -> AsyncIterator[str]:
    yield ": connected\n\n"
    async for ping in _heartbeats(request):   # fixture mode: nothing is ever live
        yield ping


@router.get("/events")
def stream_global_events(request: Request) -> StreamingResponse:
    return StreamingResponse(_global_stream(request), media_type="text/event-stream", headers=SSE_HEADERS)
