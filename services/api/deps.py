"""Shared pieces used by every router: the error type, the store and two helpers.

Kept apart from main.py so that events.py and settings.py can import them without a circular import.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from .store import CALL_ID_RE, ArtifactStore, FixtureStore

log = logging.getLogger("sentinel.api")


# --------------------------------------------------------------------------- errors
class ApiError(Exception):
    """Raised anywhere in an endpoint; turned into {"error", "detail"} with the given HTTP status."""

    def __init__(self, status: int, code: str, detail: str | list[str]):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


# --------------------------------------------------------------------------- store
def make_store() -> FixtureStore | ArtifactStore:
    """SENTINEL_FIXTURES=1 → MOCK fixtures; SENTINEL_RUN_DIR=<folder with out/ and artifacts/> → a real run."""
    if os.environ.get("SENTINEL_FIXTURES") == "1":
        return FixtureStore()
    run_dir = os.environ.get("SENTINEL_RUN_DIR")
    if run_dir:
        path = Path(run_dir).expanduser()
        if not (path / "out" / "results").is_dir():
            raise RuntimeError(f"SENTINEL_RUN_DIR={path} has no out/results/ folder: point it at the folder that "
                               "contains out/ and artifacts/ (the pipeline's output).")
        log.info("serving the pipeline run in %s", path)
        return ArtifactStore(path)
    raise RuntimeError("Choose the data: SENTINEL_FIXTURES=1 (MOCK fixtures) or "
                       "SENTINEL_RUN_DIR=<folder with out/ and artifacts/> (a real pipeline run).")


class StoreRef:
    """The current store. Routers import this one object; `use()` swaps what it points at (tests use it to
    run the same app on a fixture store and on a temporary real run)."""

    def __init__(self, target: FixtureStore | ArtifactStore):
        self._target = target

    def use(self, target: FixtureStore | ArtifactStore) -> None:
        self._target = target

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


store = StoreRef(make_store())


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


