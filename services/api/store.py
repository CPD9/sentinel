"""Where the API's data comes from.

The endpoints in main.py never open files themselves; they ask a store. Two stores with the same methods:
  FixtureStore   the MOCK documents in fixtures/ (docs/API.md "Fixture mode"), started with SENTINEL_FIXTURES=1
  ArtifactStore  a real pipeline run (docs/API.md "Files"), started with SENTINEL_RUN_DIR=<folder with out/ and artifacts/>

Label isolation (docs/API.md): no store ever opens artifacts/manifests/evaluation.json or label files.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"
# Label-free index of the calls (call_id, audio path, variant, duration). Never evaluation.json.
INFERENCE_MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "inference.json"

# Neutral call ids only (docs/API.md: anything else -> 404).
CALL_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
# Snippet file names: a plain basename ending in .wav, no "/" and no "..".
SNIPPET_NAME_RE = re.compile(r"^[\w.-]+\.wav$")

# Side documents a call can have, and the fixture file suffix for each.
DOC_KINDS = ("transcript", "trace", "analysis")


def summary(result: dict | None, trace: dict | None) -> dict:
    """The two list fields that say *why*: decision_path (from the trace; stage_error for a failed call without a
    trace) and the top finding's reason."""
    findings = [f for f in (result or {}).get("findings") or [] if isinstance(f, dict)]
    top = max(findings, key=lambda f: f.get("risk") or 0, default=None)
    path = (trace or {}).get("decision_path") or ("stage_error" if (result or {}).get("stage_errors") else None)
    return {"decision_path": path, "reason": (top or {}).get("reason")}


class FixtureStore:
    """Read-only access to fixtures/. Every document in there is invented (is_mock / versions = MOCK)."""

    is_mock = True
    mode = "fixtures"
    feedback_path: Path | None = None      # verdicts stay in memory in fixture mode

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
        """All inbox rows (CallListItem dicts), with decision_path and reason added from the call's documents."""
        rows = self._load("calls.json") or []
        return [{**r, **summary(self.get_result(r["call_id"]), self.get_doc(r["call_id"], "trace"))} for r in rows]

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


def _read_json(path: Path) -> Any | None:
    """Parsed JSON, or None when the file does not exist."""
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_out_dir(run_dir: Path) -> Path | None:
    """The run's output folder: out/, else the one out*/ folder that has results/ (a run shared as e.g. out_jules/)."""
    if (run_dir / "out" / "results").is_dir():
        return run_dir / "out"
    found = sorted(p for p in run_dir.glob("out*") if (p / "results").is_dir())
    return found[0] if len(found) == 1 else None


class ArtifactStore:
    """Read-only access to one pipeline run, in the layout process_call writes (docs/API.md "Files"):

      out/results/<call_id>.json                 CallResult (one per finished call; the call list is built from these)
      out/snippets/<call_id>/<criterion>_<n>.wav  passage snippets (±10 s)
      artifacts/transcripts/<call_id>.json        Transcript
      artifacts/traces/<call_id>.json             DecisionTrace
      artifacts/analysis/<call_id>/analysis.json  AnalysisArtifact
      artifacts/audio/<call_id>.wav               full call audio
      artifacts/quality/*.json                    QualityReport (optional)

    Officer verdicts are appended to out/feedback.jsonl. Label isolation: this store never opens
    artifacts/manifests/evaluation.json or any label file; duration and variant come from the label-free
    inference.json. Swapping the run folder (e.g. for a calibrated run) only needs a restart.
    """

    is_mock = False
    mode = "artifacts"

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.out = find_out_dir(self.run_dir) or self.run_dir / "out"
        self.art = self.run_dir / "artifacts"
        self.feedback_path: Path | None = self.out / "feedback.jsonl"
        manifest = _read_json(self.art / "manifests" / "inference.json") or _read_json(INFERENCE_MANIFEST) or {}
        self._manifest = {c["call_id"]: c for c in manifest.get("calls", []) if isinstance(c, dict) and "call_id" in c}

    # ---------------------------------------------------------------- calls
    def _result_files(self) -> list[Path]:
        d = self.out / "results"
        # *.json only: atomic writes use ".<name>.<random>.tmp" files, which this skips
        return sorted(p for p in d.glob("*.json") if not p.name.startswith(".")) if d.is_dir() else []

    def _row(self, path: Path) -> dict | None:
        """The inbox row (CallListItem) of one result file. None for a file that is not a CallResult of that id."""
        r = _read_json(path)
        if not isinstance(r, dict) or r.get("call_id") != path.stem:
            return None
        call_id = path.stem
        findings = sorted((f for f in r.get("findings") or [] if isinstance(f, dict)), key=lambda f: -(f.get("risk") or 0))
        meta = self._manifest.get(call_id, {})
        duration = meta.get("duration_s")
        if duration is None:
            t = self.get_doc(call_id, "transcript")
            duration = t.get("duration_s") if t else None
        errors = r.get("stage_errors") or []
        return {
            "call_id": call_id,
            "status": "error" if errors else "done",
            "duration_s": duration,
            "variant": meta.get("variant"),
            "decision": r.get("decision"),
            "risk_score": r.get("risk_score"),
            "confidence": r.get("confidence"),
            "criteria": list(dict.fromkeys(f["criterion"] for f in findings if f.get("criterion"))),
            "n_stage_errors": len(errors),
            "updated_at": _iso_mtime(path),
            "is_mock": False,
            **summary(r, self.get_doc(call_id, "trace")),
        }

    def list_calls(self) -> list[dict]:
        rows = (self._row(p) for p in self._result_files())
        return [r for r in rows if r is not None]

    def get_row(self, call_id: str) -> dict | None:
        path = self.out / "results" / f"{call_id}.json"
        return self._row(path) if path.is_file() else None

    def get_result(self, call_id: str) -> dict | None:
        return _read_json(self.out / "results" / f"{call_id}.json")

    def get_doc(self, call_id: str, kind: str) -> dict | None:
        if kind not in DOC_KINDS:
            raise ValueError(f"unknown document kind {kind!r}")
        if kind == "analysis":
            return _read_json(self.art / "analysis" / call_id / "analysis.json")
        folder = "transcripts" if kind == "transcript" else "traces"
        # ASR runs write transcripts/ and traces/; runs on reference transcripts write *_reference/ instead
        # (pipeline/runner.py _paths). Read only the folder that belongs to the call's result, never the other mode's
        # document: it would come from another run (other segment ids, other facts, other decision).
        if self._is_reference_run(call_id):
            folder += "_reference"
        return _read_json(self.art / folder / f"{call_id}.json")

    def _is_reference_run(self, call_id: str) -> bool:
        result = self.get_result(call_id) or {}
        return str((result.get("versions") or {}).get("asr") or "").startswith("reference")

    def get_events(self, call_id: str) -> list[dict] | None:
        """Finished runs keep no event log; the API synthesizes a short one from the result."""
        return None

    # ---------------------------------------------------------------- audio
    def audio_path(self, call_id: str) -> Path | None:
        p = self.art / "audio" / f"{call_id}.wav"
        return p if p.is_file() else None

    def snippet_path(self, call_id: str, name: str) -> Path | None:
        """`name` is already checked against SNIPPET_NAME_RE by the endpoint; resolve strictly inside the call's folder."""
        folder = (self.out / "snippets" / call_id).resolve()
        p = (folder / name).resolve()
        return p if p.parent == folder and p.is_file() else None

    # ---------------------------------------------------------------- quality
    def _reports(self) -> list[dict]:
        d = self.art / "quality"
        docs = [_read_json(p) for p in sorted(d.glob("*.json"))] if d.is_dir() else []
        return [r for r in docs if isinstance(r, dict) and "report_id" in r]

    def list_quality(self) -> list[dict]:
        keys = ("report_id", "run_id", "split", "mode", "system", "created_at", "is_mock")
        rows = [{k: r.get(k) for k in keys} for r in self._reports()]
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    def get_quality(self, report_id: str) -> dict | None:
        return next((r for r in self._reports() if r["report_id"] == report_id), None)
