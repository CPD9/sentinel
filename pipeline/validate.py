"""Step 5: evidence validator. Facts are never deleted: a failing fact gets valid=False and a short drop_reason, so
decide.py can raise the "missing evidence" signal and the UI can show why.

Checks, first failure wins (reasons are stable strings, the run report counts them):
  empty quote -> unknown segment id -> quote not found in the cited segments -> speaker mismatch.
Ids are resolved like parse-twin-answer's resolveAttribution: exact, then case-insensitive (brackets and spaces
stripped). No numeric guessing: "T1" does not resolve to "T001".
"""
from __future__ import annotations

import re
from dataclasses import replace
from difflib import SequenceMatcher

from pipeline.schemas import Fact, Transcript

QUOTE_MATCH_MIN = 0.8        # share of the quote's characters found in order in one cited segment
NO_CITATION = "<none>"

R_EMPTY = "empty quote"
R_UNKNOWN_ID = "unknown segment id"
R_NO_CITATION = "no segment ids cited"
R_FIELD = "invalid field"
R_QUOTE = "quote not in cited segments"
R_SPEAKER = "speaker mismatch"
REASON_KEYS = (R_FIELD, R_EMPTY, R_UNKNOWN_ID, R_NO_CITATION, R_QUOTE, R_SPEAKER)


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def resolve_id(raw: str, ids: set[str], lower: dict[str, str]) -> str | None:
    key = raw.strip().strip("[]() ").strip()
    if key in ids:
        return key
    return lower.get(key.lower())


def resolver(transcript: Transcript):
    ids = {s.id for s in transcript.segments}
    lower: dict[str, str] = {}
    for i in sorted(ids):
        lower.setdefault(i.lower(), i)
    return lambda raw: resolve_id(raw, ids, lower)


def quote_coverage(quote: str, segment_text: str) -> float:
    """Fraction of the (normalised) quote matched in order inside the (normalised) segment."""
    q, s = norm(quote), norm(segment_text)
    if not q:
        return 0.0
    if q in s:
        return 1.0
    sm = SequenceMatcher(None, q, s, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(q)


def drop(fact: Fact, reason: str) -> Fact:
    return replace(fact, valid=False, drop_reason=reason)


def validate_facts(facts: list[Fact], transcript: Transcript) -> list[Fact]:
    """Returns every fact, with valid / drop_reason set. Facts already invalid keep their first reason."""
    by_id = {s.id: s for s in transcript.segments}
    resolve = resolver(transcript)
    out = []
    for f in facts:
        if not f.valid:
            out.append(f)
            continue
        if not f.quote or not f.quote.strip():
            out.append(drop(f, R_EMPTY))
            continue
        cited = [s for s in f.segment_ids if s and s != NO_CITATION]
        if not cited:
            out.append(drop(f, R_NO_CITATION))
            continue
        resolved = [resolve(s) for s in cited]
        bad = [s for s, r in zip(cited, resolved) if r is None]
        if bad:
            out.append(drop(f, f"{R_UNKNOWN_ID}: {', '.join(bad)}"))
            continue
        ids = list(dict.fromkeys(resolved))
        segs = [by_id[i] for i in ids]
        scored = sorted(((quote_coverage(f.quote, s.text), s) for s in segs), key=lambda x: -x[0])
        best, best_seg = scored[0]
        if best < QUOTE_MATCH_MIN:
            out.append(drop(replace(f, segment_ids=ids), f"{R_QUOTE} ({best:.2f})"))
            continue
        if best_seg.speaker != "unknown" and f.speaker != "unknown" and best_seg.speaker != f.speaker:
            out.append(drop(replace(f, segment_ids=ids), f"{R_SPEAKER}: fact {f.speaker}, segment {best_seg.id} {best_seg.speaker}"))
            continue
        out.append(replace(f, segment_ids=ids))
    return out


def reason_key(drop_reason: str | None) -> str | None:
    """Stable bucket of a drop_reason for counting (strips the ids / numbers after the colon or bracket)."""
    if not drop_reason:
        return None
    for k in REASON_KEYS:
        if drop_reason.startswith(k):
            return k
    return "other"
