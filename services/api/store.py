"""Where the API's data comes from.

The endpoints in main.py never open files themselves; they ask a store. Today there is one store,
`FixtureStore`, which serves the MOCK documents in fixtures/ (docs/API.md "Fixture mode"). When the
pipeline milestone lands, an `ArtifactStore` with the same methods will read out/results/ and
artifacts/ instead, and main.py will not need to change.

Label isolation (docs/API.md): no store ever opens artifacts/manifests/evaluation.json or label files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"

# Neutral call ids only (docs/API.md: anything else -> 404).
CALL_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
# Snippet file names: a plain basename ending in .wav, no "/" and no "..".
SNIPPET_NAME_RE = re.compile(r"^[\w.-]+\.wav$")

# Side documents a call can have, and the fixture file suffix for each.
DOC_KINDS = ("transcript", "trace", "analysis")


class FixtureStore:
    """Read-only access to fixtures/. Every document in there is invented (is_mock / versions = MOCK)."""

    is_mock = True
    mode = "fixtures"

    def __init__(self, root: Path = FIXTURES_DIR):
        self.root = root

    # ---------------------------------------------------------------- helpers
    def _load(self, name: str) -> Any | None:
        """Parsed JSON of fixtures/<name>, or None when the file does not exist."""
        path = self.root / name
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- calls
    def list_calls(self) -> list[dict]:
        """All inbox rows (CallListItem dicts)."""
        return self._load("calls.json") or []

    def get_row(self, call_id: str) -> dict | None:
        """One inbox row, or None for an unknown call."""
        return next((c for c in self.list_calls() if c["call_id"] == call_id), None)

    def get_result(self, call_id: str) -> dict | None:
        """The CallResult of a finished call, or None if there is none (yet)."""
        return self._load(f"{call_id}.result.json")

    def get_doc(self, call_id: str, kind: str) -> dict | None:
        """transcript / trace / analysis of one call, or None if that document does not exist."""
        if kind not in DOC_KINDS:
            raise ValueError(f"unknown document kind {kind!r}")
        return self._load(f"{call_id}.{kind}.json")

    def get_events(self, call_id: str) -> list[dict] | None:
        """Recorded ProcessingEvents of one call, or None if no event log exists."""
        return self._load(f"{call_id}.events.json")

    # ---------------------------------------------------------------- audio
    def audio_path(self, call_id: str) -> Path | None:
        """Fixture mode has no audio (*.wav is gitignored), so audio endpoints answer 404."""
        return None

    def snippet_path(self, call_id: str, name: str) -> Path | None:
        return None

    # ---------------------------------------------------------------- quality
    def _report(self) -> dict | None:
        return self._load("quality_report.json")

    def list_quality(self) -> list[dict]:
        """Report summaries, newest first. Same shape as in normal mode (a list)."""
        r = self._report()
        if r is None:
            return []
        keys = ("report_id", "run_id", "split", "mode", "system", "created_at", "is_mock")
        return [{k: r.get(k) for k in keys}]

    def get_quality(self, report_id: str) -> dict | None:
        r = self._report()
        return r if r is not None and r.get("report_id") == report_id else None
