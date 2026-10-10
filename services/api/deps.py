"""Shared pieces used by every router: the error type, the store and two helpers.

Kept apart from main.py so that events.py and settings.py can import them without a circular import.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

from .store import CALL_ID_RE, FixtureStore

log = logging.getLogger("sentinel.api")


# --------------------------------------------------------------------------- errors
class ApiError(Exception):
    """Raised anywhere in an endpoint; turned into {"error", "detail"} with the given HTTP status."""

    def __init__(self, status: int, code: str, detail: str | list[str]):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


# --------------------------------------------------------------------------- store
def make_store() -> FixtureStore:
    if os.environ.get("SENTINEL_FIXTURES") == "1":
        return FixtureStore()
    raise RuntimeError(
        "Only fixture mode exists so far: start the API with SENTINEL_FIXTURES=1. "
        "Real mode (reading pipeline results) arrives with the process_call() milestone."
    )


store = make_store()


# --------------------------------------------------------------------------- helpers
def checked(doc: Any, validate: Callable[[Any], list[str]], what: str) -> Any:
    """Validate a document before serving it. A broken artifact is logged and served as 500, so the
    UI shows its error state instead of crashing (docs/API.md "Validation")."""
    errors = validate(doc)
    if errors:
        log.error("%s failed schema validation: %s", what, errors)
        raise ApiError(500, "internal", [f"{what}: {e}" for e in errors])
    return doc


def known_call(call_id: str) -> dict:
    """The inbox row of a call. Malformed or unknown ids are 404 not_found."""
    if not CALL_ID_RE.match(call_id):
        raise ApiError(404, "not_found", f"Unknown call {call_id!r}")
    row = store.get_row(call_id)
    if row is None:
        raise ApiError(404, "not_found", f"Unknown call {call_id!r}")
    return row


def side_doc(call_id: str, kind: str, validate: Callable[[Any], list[str]]) -> dict:
    """transcript / trace / analysis of a known call; a missing document is 404 not_available."""
    known_call(call_id)
    doc = store.get_doc(call_id, kind)
    if doc is None:
        raise ApiError(404, "not_available", f"{kind.capitalize()} not available for {call_id}")
    return checked(doc, validate, f"{call_id} {kind}")


