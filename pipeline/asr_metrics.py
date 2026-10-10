"""ASR quality measures shared by scripts/benchmark_asr.py and the tests (stdlib only).

  normalise(text)              casefold, NFC, ß -> ss, punctuation/hyphens -> space, collapse spaces
  wer(ref, hyp) / cer(...)     Levenshtein on normalised words / characters (spaces excluded)
  keyword_recall(...)          keyword concepts (de OR gsw variant) said in the reference that the
                               hypothesis also contains, fuzzy-matched like pipeline/keywords.py will
  timestamp_sanity(...)        are segment/word times usable as audio evidence?
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

FUZZY_THRESHOLD = 0.85
EXACT_MAX_LEN = 4            # terms this short (PIN, TAN) must match a whole token exactly
TIME_TOLERANCE_S = 0.05      # same tolerance as pipeline/schemas.py
OVERLAP_TOLERANCE_S = 0.2

_PUNCT_RE = re.compile(r"[^\w\s]|_")
_SPACE_RE = re.compile(r"\s+")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFC", text).casefold().replace("ß", "ss")
    t = t.replace("-", " ").replace("'", "").replace("’", "")
    return _SPACE_RE.sub(" ", _PUNCT_RE.sub(" ", t)).strip()


def _edit_distance(a: list, b: list) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def error_counts(ref: str, hyp: str, unit: str = "word") -> tuple[int, int]:
    """(edit errors, reference length) after normalisation. unit: 'word' or 'char'."""
    r, h = normalise(ref), normalise(hyp)
    if unit == "word":
        rs, hs = r.split(), h.split()
    else:
        rs, hs = list(r.replace(" ", "")), list(h.replace(" ", ""))
    return _edit_distance(rs, hs), len(rs)


def _rate(ref: str, hyp: str, unit: str) -> float | None:
    errs, n = error_counts(ref, hyp, unit)
    return errs / n if n else None          # None = empty reference, undefined


def wer(ref: str, hyp: str) -> float | None:
    return _rate(ref, hyp, "word")


def cer(ref: str, hyp: str) -> float | None:
    return _rate(ref, hyp, "char")


# --------------------------------------------------------------------------- keywords

def keyword_terms(keyword_list: dict) -> dict[str, list[str]]:
    """Stichwortliste.json -> {keyword id: normalised de + gsw variants} for enabled keywords."""
    out = {}
    for k in keyword_list["keywords"]:
        if k.get("enabled", True):
            out[k["id"]] = sorted({normalise(t) for t in k.get("de", []) + k.get("gsw", []) if normalise(t)})
    return out


def count_term(text_norm: str, term_norm: str, threshold: float = FUZZY_THRESHOLD) -> int:
    """Non-overlapping occurrences of a (multi-word) term in normalised text, fuzzy per token window."""
    toks, n = text_norm.split(), len(term_norm.split())
    if not toks or n == 0:
        return 0
    exact = len(term_norm) <= EXACT_MAX_LEN
    hits, i = 0, 0
    while i <= len(toks) - n:
        best = 0.0
        for w in ({n} if exact else {n, n + 1, max(1, n - 1)}):
            cand = " ".join(toks[i:i + w])
            if exact:
                best = max(best, float(cand == term_norm))
            else:
                best = max(best, SequenceMatcher(None, cand, term_norm).ratio())
        if best >= threshold:
            hits += 1
            i += n
        else:
            i += 1
    return hits


def keyword_counts(text: str, terms: dict[str, list[str]]) -> dict[str, int]:
    t = normalise(text)
    return {kid: sum(count_term(t, v) for v in variants) for kid, variants in terms.items()}


def keyword_recall(ref: str, hyp: str, terms: dict[str, list[str]]) -> dict:
    """Presence recall: keyword ids said in the reference that the hypothesis also contains (any
    variant). Occurrence recall: sum(min(hyp, ref)) / sum(ref) over the same ids."""
    rc, hc = keyword_counts(ref, terms), keyword_counts(hyp, terms)
    present = [k for k, c in rc.items() if c]
    found = [k for k in present if hc[k]]
    occ_ref = sum(rc[k] for k in present)
    occ_hit = sum(min(rc[k], hc[k]) for k in present)
    return {
        "ref_keywords": present, "found": found, "missed": [k for k in present if k not in found],
        "presence_hits": len(found), "presence_total": len(present),
        "occurrence_hits": occ_hit, "occurrence_total": occ_ref,
    }


# --------------------------------------------------------------------------- timestamps

def timestamp_sanity(segments: list[dict], duration_s: float) -> dict:
    """segments: [{start, end, words?: [{start, end}]}]. Fractions are of segments (or words)."""
    n = len(segments)
    if n == 0:
        return {"n_segments": 0, "valid_span_frac": None, "monotonic": True, "n_overlaps": 0,
                "max_gap_s": None, "word_inside_frac": None, "coverage_frac": 0.0, "ok": False}
    valid = sum(1 for s in segments if 0 <= s["start"] < s["end"] <= duration_s + TIME_TOLERANCE_S)
    starts = [s["start"] for s in segments]
    monotonic = all(b >= a for a, b in zip(starts, starts[1:]))
    overlaps = sum(1 for a, b in zip(segments, segments[1:]) if b["start"] < a["end"] - OVERLAP_TOLERANCE_S)
    gaps = [b["start"] - a["end"] for a, b in zip(segments, segments[1:])]
    gaps = [segments[0]["start"]] + gaps + [duration_s - segments[-1]["end"]]
    words = [(s, w) for s in segments for w in s.get("words") or []]
    inside = sum(1 for s, w in words if s["start"] - TIME_TOLERANCE_S <= w["start"] <= w["end"]
                 <= s["end"] + TIME_TOLERANCE_S)
    covered = sum(max(0.0, min(s["end"], duration_s) - max(s["start"], 0.0)) for s in segments)
    out = {
        "n_segments": n,
        "valid_span_frac": valid / n,
        "monotonic": monotonic,
        "n_overlaps": overlaps,
        "max_gap_s": round(max(gaps), 3),
        "word_inside_frac": inside / len(words) if words else None,
        "coverage_frac": round(min(1.0, covered / duration_s), 4) if duration_s > 0 else None,
    }
    out["ok"] = (out["valid_span_frac"] == 1.0 and monotonic and overlaps == 0
                 and (out["word_inside_frac"] is None or out["word_inside_frac"] >= 0.99))
    return out
