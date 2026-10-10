"""Inference-side loader for reference-transcript mode (organizer scripts instead of our ASR).

Reads only artifacts/manifests/reference_transcripts.json, written by scripts/prepare_data.py:
neutral call_id -> [{segment_id, speaker, text}]. That file holds no labels, levels, titles,
original file names or dialogue ids, so inference never needs the label manifest.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_FILE = REPO_ROOT / "artifacts" / "manifests" / "reference_transcripts.json"


def load_reference_transcripts(path: Path = REFERENCE_FILE) -> dict[str, list[dict]]:
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run scripts/prepare_data.py")
    return json.loads(path.read_text(encoding="utf-8"))["calls"]


def reference_transcript(call_id: str, path: Path = REFERENCE_FILE) -> list[dict]:
    """Script turns of one call: [{segment_id, speaker, text}]."""
    turns = load_reference_transcripts(path).get(call_id)
    if not turns:
        raise ValueError(f"{call_id}: no reference transcript in {path}")
    return [{"segment_id": t["segment_id"], "speaker": t["speaker"], "text": t["text"]} for t in turns]
