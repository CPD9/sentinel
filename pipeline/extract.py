"""Step 4: LLM fact extraction over the WHOLE transcript, in overlapping windows, then the evidence validator.

    extract_facts(transcript: Transcript) -> list[Fact]       (contract with pipeline/stages.py; raises on failure)

The LLM comes from the provider registry (`llm.get_client`; default = our vLLM via LLM_BASE_URL / LLM_MODEL, or
$SENTINEL_LLM_PROVIDER). Temperature 0, JSON schema constrained, one answer per window, cached per window by
`llm.extraction_cache_key` (transcript content + provider + model id/revision + prompt version + runtime). Keyword
hits and config files are never inputs, so editing them never invalidates the cache.

Failure policy: a reply that is not the JSON object we asked for gets exactly one repair call, then
`ExtractionError`. A single bad fact (invalid enum, unresolvable segment id, quote not in the cited lines) is
kept with valid=False and a reason: it is evidence that was lost, not a reason to fail the call.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import replace
from pathlib import Path

from pipeline import llm
from pipeline.llm import DiskCache, extraction_cache_key
from pipeline.prompts import extract_v1, extract_v2
from pipeline.schemas import FACT_ACTS, INFO_TYPES, SPEAKERS, Fact, Transcript, TranscriptSegment
from pipeline.validate import NO_CITATION, R_FIELD, norm, resolver, validate_facts

CACHE_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "cache" / "extract"

# Token budget of the self-hosted model (max context 8192): prompt ~900 + window + output must stay well below.
CONTEXT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 1500
WINDOW_TOKENS = 3500         # estimated tokens of transcript text per window
CHARS_PER_TOKEN = 2.5        # deliberately pessimistic for Swiss German (real usage is reported by the run script)
OVERLAP_SEGMENTS = 4

PROMPTS = {"v1": extract_v1, "v2": extract_v2}


def max_output_tokens(p=None) -> int:
    """Answer budget of a prompt generation (v1 keeps the module default so its cached runs stay valid)."""
    return getattr(p or prompt, "MAX_OUTPUT_TOKENS", MAX_OUTPUT_TOKENS)


def window_tokens(p=None) -> int:
    """Transcript budget per window for a prompt generation (v1 keeps the module default)."""
    return getattr(p or prompt, "WINDOW_TOKENS", WINDOW_TOKENS)


def _prompt_hash(p) -> str:
    """Version suffix: any edit to the text, schema, window constants (and, for v2, the user-message template)
    invalidates the cache even without a version bump. The v1 formula is frozen so its cached runs stay valid."""
    parts = [p.SYSTEM_PROMPT, p.FACT_SCHEMA, CHARS_PER_TOKEN, window_tokens(p), OVERLAP_SEGMENTS, max_output_tokens(p)]
    if p is not extract_v1:
        parts.append(inspect.getsource(p.user_message))
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:8]


prompt = extract_v2
PROMPT_VERSION = prompt.PROMPT_VERSION
PROMPT_VERSION_FULL = PROMPT_VERSION + "+" + _prompt_hash(prompt)


def set_prompt(name: str) -> None:
    """Select the prompt generation ("v1" | "v2") for this process (scripts/run_extract.py --prompt)."""
    global prompt, PROMPT_VERSION, PROMPT_VERSION_FULL
    prompt = PROMPTS[name]
    PROMPT_VERSION = prompt.PROMPT_VERSION
    PROMPT_VERSION_FULL = PROMPT_VERSION + "+" + _prompt_hash(prompt)
    VERSIONS["prompt"] = PROMPT_VERSION_FULL


# Read by pipeline/stages.py after a successful extraction.
VERSIONS: dict = {"llm": None, "prompt": PROMPT_VERSION_FULL, "provider": None, "self_hosted": None}


class TruncatedReply(ValueError):
    """The reply hit max_tokens: too many facts for one window. extract_facts splits the window and retries."""


class ExtractionError(RuntimeError):
    pass


# --------------------------------------------------------------------------- windows

def _cost(s: TranscriptSegment) -> float:
    return (len(s.id) + len(s.speaker) + len(s.text) + 8) / CHARS_PER_TOKEN


def make_windows(segments: list[TranscriptSegment]) -> list[list[TranscriptSegment]]:
    """Greedy windows on segment boundaries, each <= WINDOW_TOKENS (a single oversized segment stands alone),
    consecutive windows sharing OVERLAP_SEGMENTS segments. Every segment is in at least one window."""
    n, out, start = len(segments), [], 0
    while start < n:
        end, used = start, 0.0
        while end < n and (end == start or used + _cost(segments[end]) <= window_tokens()):
            used += _cost(segments[end])
            end += 1
        out.append(segments[start:end])
        if end >= n:
            break
        start = max(end - OVERLAP_SEGMENTS, start + 1)
    return out


# --------------------------------------------------------------------------- reply parsing

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def clean_reply(text: str) -> str:
    """Drop reasoning blocks and code fences from a model reply."""
    text = _THINK.sub("", text)
    i = text.lower().find("<think>")        # unclosed block: the answer never started
    if i >= 0:
        text = text[:i]
    return re.sub(r"```(?:json)?", "", text).strip()


def parse_reply(text: str) -> list:
    """The `facts` list of a reply. ValueError when the reply is not the object we asked for."""
    text = clean_reply(text)
    try:
        obj = json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b <= a:
            raise ValueError("no JSON object in the reply") from None
        try:
            obj = json.loads(text[a:b + 1])
        except ValueError as e:
            raise ValueError(f"invalid JSON: {e}") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("facts"), list):
        raise ValueError('reply is not an object with a "facts" list')
    return obj["facts"]


# --------------------------------------------------------------------------- one window

def _call(client, messages: list[dict], metrics: list[dict]) -> str:
    text, m = client.chat_with_metrics(messages, temperature=0.0, max_tokens=max_output_tokens(),
                                       json_schema=prompt.FACT_SCHEMA)
    metrics.append(m.to_dict())
    return text


def _window_raw(client, cache: DiskCache, window: list[TranscriptSegment]) -> dict:
    """{facts: [raw dicts], repaired, cached, metrics: [...]} for one window."""
    segs = [{"id": s.id, "speaker": s.speaker, "text": s.text} for s in window]
    key = extraction_cache_key(segs, client.model, client.model_revision, PROMPT_VERSION_FULL, provider=client.spec.name)
    hit = cache.get(key)
    if hit is not None:
        return {"facts": parse_reply(hit["response"]), "repaired": hit["repaired"], "cached": True,
                "metrics": hit["metrics"]}
    messages = [{"role": "system", "content": prompt.SYSTEM_PROMPT},
                {"role": "user", "content": prompt.user_message(segs)}]
    metrics: list[dict] = []
    text, repaired = _call(client, messages, metrics), False
    try:
        facts = parse_reply(text)
    except ValueError as first:
        if metrics[-1].get("output_tokens") is not None and metrics[-1]["output_tokens"] >= max_output_tokens():
            # cut off at the token limit: a repair call would have to carry the whole reply and cannot fit the context
            raise TruncatedReply(f"model reply is not valid JSON: {first} (reply hit the max_tokens limit: truncated)") from None
        repaired = True
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": f"That answer was not usable ({first}). Answer again with ONLY the "
                                                 'JSON object {"facts": [...]} in the format described.'}]
        text = _call(client, messages, metrics)
        try:
            facts = parse_reply(text)
        except ValueError as second:
            cut = metrics[-1].get("output_tokens") is not None and metrics[-1]["output_tokens"] >= max_output_tokens()
            raise ExtractionError(f"model reply is not valid JSON after one repair attempt: {second}"
                                  f"{' (reply hit the max_tokens limit: truncated)' if cut else ''}") from None
    cache.put(key, {"response": text, "repaired": repaired, "metrics": metrics, "prompt_version": PROMPT_VERSION_FULL,
                    "provider": client.spec.name, "model": client.model, "revision": client.model_revision})
    return {"facts": facts, "repaired": repaired, "cached": False, "metrics": metrics}


# --------------------------------------------------------------------------- raw dict -> Fact

def _flag(v):
    return v if isinstance(v, bool) else None


def to_fact(raw, resolve) -> Fact:
    """Lenient conversion: whatever is wrong becomes valid=False + reason, with enum fields coerced so the
    DecisionTrace stays schema-valid."""
    if not isinstance(raw, dict):
        return Fact("", "unknown", "other", "other", [NO_CITATION], "", valid=False,
                    drop_reason=f"{R_FIELD}: fact is not an object")
    problems = []

    def enum(key, allowed, default):
        v = raw.get(key)
        if v in allowed:
            return v
        problems.append(f"{key} {v!r}")
        return default

    speaker = enum("speaker", SPEAKERS, "unknown")
    act = enum("act", FACT_ACTS, "other")
    info = enum("info_type", INFO_TYPES, "other")
    ids = raw.get("segment_ids")
    ids = [ids] if isinstance(ids, str) else ids if isinstance(ids, list) else []
    ids = [i for i in ids if isinstance(i, str) and i.strip()]
    cited = list(dict.fromkeys(resolve(i) or i.strip() for i in ids)) or [NO_CITATION]
    ce, gloss = raw.get("counter_evidence"), raw.get("gloss_de")
    return Fact(
        fact_id="", speaker=speaker, act=act, info_type=info, segment_ids=cited,
        quote=raw["quote"].strip() if isinstance(raw.get("quote"), str) else "",
        recipient_third_party=_flag(raw.get("recipient_third_party")), secrecy_cue=_flag(raw.get("secrecy_cue")),
        counter_evidence=ce.strip() or None if isinstance(ce, str) else None,
        gloss_de=gloss.strip() or None if isinstance(gloss, str) else None,
        valid=not problems, drop_reason=f"{R_FIELD}: {', '.join(problems)}" if problems else None)


def check_span(f: Fact, pos: dict[str, int]) -> Fact:
    """v2 rule: a fact cites at most MAX_SEGMENT_IDS segments and they are adjacent in the transcript (no ranges,
    no scattered ids). Violations are kept as invalid facts, like any other bad field. v1 has no such rule."""
    limit = getattr(prompt, "MAX_SEGMENT_IDS", None)
    if not limit or not f.valid or f.segment_ids == [NO_CITATION]:
        return f
    where = sorted(pos[i] for i in f.segment_ids if i in pos)
    if len(f.segment_ids) > limit:
        why = f"cites {len(f.segment_ids)} segments (max {limit})"
    elif len(where) == len(f.segment_ids) and where[-1] - where[0] != len(where) - 1:
        why = "cites segments that are not adjacent"
    else:
        return f
    return replace(f, valid=False, drop_reason=f"{R_FIELD}: {why}")


# --------------------------------------------------------------------------- merge

def _same(a: Fact, b: Fact) -> bool:
    if (a.speaker, a.act, a.info_type, a.recipient_third_party, a.secrecy_cue, a.valid) != \
            (b.speaker, b.act, b.info_type, b.recipient_third_party, b.secrecy_cue, b.valid):
        return False
    return bool(set(a.segment_ids) & set(b.segment_ids)) or (bool(norm(a.quote)) and norm(a.quote) == norm(b.quote))


def merge_facts(facts: list[Fact], transcript: Transcript) -> list[Fact]:
    """Duplicates from overlapping windows become one fact; ids are renumbered f001... in transcript order."""
    pos = {s.id: i for i, s in enumerate(transcript.segments)}
    at = lambda ids: sorted(ids, key=lambda i: (pos.get(i, len(pos)), i))
    merged: list[Fact] = []
    for f in facts:
        for k, m in enumerate(merged):
            if _same(m, f):
                longer = f if len(f.quote) > len(m.quote) else m
                merged[k] = replace(m, segment_ids=at(set(m.segment_ids) | set(f.segment_ids)), quote=longer.quote,
                                    gloss_de=longer.gloss_de or m.gloss_de or f.gloss_de,
                                    counter_evidence=m.counter_evidence or f.counter_evidence)
                break
        else:
            merged.append(replace(f, segment_ids=at(f.segment_ids)))
    merged.sort(key=lambda f: pos.get(f.segment_ids[0], len(pos)))
    return [replace(f, fact_id=f"f{i:03d}") for i, f in enumerate(merged, 1)]


# --------------------------------------------------------------------------- entry point

def extract_facts(transcript: Transcript, *, client=None, cache: DiskCache | None = None,
                  report: list | None = None) -> list[Fact]:
    """Validated facts of one call (valid / drop_reason set; dropped facts are kept).

    `client` / `cache` are for tests and scripts; by default the registry's client and artifacts/cache/extract.
    `report`, when given, receives one dict per window: n_segments, cached, repaired, metrics[]."""
    client = client or llm.get_client()
    if client.model_revision is None:
        client.probe()
    cache = cache or DiskCache(CACHE_DIR)
    VERSIONS.update(llm=f"{client.model}@{client.model_revision}", prompt=PROMPT_VERSION_FULL,
                    provider=client.spec.name, self_hosted=client.spec.self_hosted)
    resolve = resolver(transcript)
    pos = {s.id: i for i, s in enumerate(transcript.segments)}
    raw: list[Fact] = []
    for w, window in enumerate(make_windows(transcript.segments)):
        for res in _window_or_halves(client, cache, window):
            if report is not None:
                report.append({"window": w, "n_segments": res["n_segments"], "n_facts_raw": len(res["facts"]),
                               "cached": res["cached"], "repaired": res["repaired"], "split": res["split"],
                               "metrics": res["metrics"]})
            raw += [check_span(to_fact(r, resolve), pos) for r in res["facts"]]
    return validate_facts(merge_facts(raw, transcript), transcript)


def _window_or_halves(client, cache: DiskCache, window: list[TranscriptSegment], depth: int = 0) -> list[dict]:
    """A window whose reply hits max_tokens (a model listing more facts than fit) is split in two halves and each
    is extracted on its own, recursively; a single segment that still truncates is an ExtractionError. Windows
    that fit are untouched, so their cache keys (and cached runs) stay valid."""
    try:
        return [{**_window_raw(client, cache, window), "n_segments": len(window), "split": depth > 0}]
    except TruncatedReply as e:
        if len(window) < 2:
            raise ExtractionError(str(e)) from None
        mid = len(window) // 2
        return (_window_or_halves(client, cache, window[:mid], depth + 1)
                + _window_or_halves(client, cache, window[mid:], depth + 1))
