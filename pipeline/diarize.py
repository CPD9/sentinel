"""Speaker roles (advisor | customer | unknown) per ASR segment. DISPLAY ONLY: never feeds the decision.

Two label sources, recorded per call:
  "acoustic + content": pyannote/speaker-diarization-3.1 clusters (scripts/pod_diarize.py on the Pod) joined to
                        the ASR segments by time overlap; Apertus then decides which cluster is the advisor from
                        content (greeting with the bank name, who asks to buy or transfer).
  "content only":       Apertus labels every segment from the text alone, in overlapping windows.

Apertus is called one request at a time through llm.get_client(), temperature 0, JSON schema, cached on disk
by transcript content + model + prompt version. The prompt sees only ASR text and neutral call ids.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline import llm
from pipeline.llm import DiskCache

PROMPT_VERSION = "speakers-v1"
CACHE_DIR = Path("artifacts/cache/speakers")
MIXED_SHARE = 0.30
MIN_VOICE_SHARE = 0.10        # minority voice below this share of words = degenerate clustering -> content only
WINDOW, OVERLAP = 40, 5
CUE_RE = re.compile(r"bank|grüe|grüezi|guete tag|kauf|verkauf|überweis|auftrag|aktie|konto|zahl|"
                    r"wie kann ich|was kann ich|chan ich", re.I)

MAP_SYSTEM = (
    "You read an automatic transcript of a Swiss bank phone call between a bank advisor and a customer. "
    "Each line is tagged with an anonymous voice cluster from acoustic diarization. Decide which cluster is the "
    "BANK ADVISOR. Cues: the advisor answers the phone with the bank's name and their own name, offers help, "
    "explains products, checks identity, and executes orders. The customer calls in, describes their situation, "
    "and asks to buy, sell or transfer. Answer in JSON only."
)
LABEL_SYSTEM = (
    "You read part of an automatic transcript of a Swiss bank phone call between a bank advisor and a customer. "
    "Speaker turns are not marked. For EVERY line, say who most likely said it: \"advisor\" (answers with the "
    "bank's name, offers help, explains, checks identity, executes orders) or \"customer\" (calls in, describes "
    "their situation, asks to buy, sell or transfer). Use \"unknown\" only if there is no cue at all. "
    "Turns usually alternate between question and answer. Answer in JSON only."
)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def join_turns(segments: list[dict], turns: list[dict]) -> list[dict]:
    """Each ASR segment gets the acoustic cluster with the largest time overlap.

    Returns [{id, cluster, overlap_frac, mixed}]; cluster is None when no turn overlaps the segment."""
    out = []
    for s in segments:
        st, en = float(s["start_s"]), float(s["end_s"])
        by: dict[str, float] = {}
        for t in turns:
            ov = _overlap(st, en, t["start_s"], t["end_s"])
            if ov > 0:
                by[t["cluster"]] = by.get(t["cluster"], 0.0) + ov
        if not by:
            out.append({"id": s["id"], "cluster": None, "overlap_frac": 0.0, "mixed": False})
            continue
        ranked = sorted(by.items(), key=lambda kv: -kv[1])
        dur = max(en - st, 1e-6)
        out.append({"id": s["id"], "cluster": ranked[0][0], "overlap_frac": round(min(ranked[0][1] / dur, 1.0), 3),
                    "mixed": len(ranked) > 1 and ranked[1][1] / dur > MIXED_SHARE})
    return out


def _ask(client, cache: DiskCache, step: str, system: str, user: str, schema: dict, max_tokens: int) -> dict:
    key = DiskCache.key({"step": step, "user": user, "system": system, "provider": client.spec.name,
                         "model": client.model, "revision": client.model_revision, "prompt_version": PROMPT_VERSION,
                         "runtime": llm.RUNTIME_VERSION})
    hit = cache.get(key)
    if hit is not None:
        return json.loads(hit["response"])
    text, m = client.chat_with_metrics([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                       temperature=0.0, max_tokens=max_tokens, json_schema=schema)
    obj = json.loads(text[text.find("{"): text.rfind("}") + 1])      # raises on an unusable answer: never cached
    cache.put(key, {"response": json.dumps(obj, ensure_ascii=False), "metrics": [m.to_dict()],
                    "prompt_version": PROMPT_VERSION, "model": client.model})
    return obj


def map_clusters(segments: list[dict], joined: list[dict], *, client, cache: DiskCache) -> tuple[dict, str]:
    """{cluster: role} for the two most-speaking clusters, plus Apertus' rationale."""
    cl = {j["id"]: j["cluster"] for j in joined}
    words: dict[str, int] = {}
    for s in segments:
        if cl.get(s["id"]):
            words[cl[s["id"]]] = words.get(cl[s["id"]], 0) + len(s["text"].split())
    clusters = sorted(words, key=lambda c: -words[c])[:2]
    if len(clusters) < 2:
        raise ValueError(f"need two clusters with speech, got {clusters}")
    share = words[clusters[1]] / (words[clusters[0]] + words[clusters[1]])
    if share < MIN_VOICE_SHARE:
        raise ValueError(f"second voice has only {share:.0%} of the words")
    keep = [s for i, s in enumerate(segments) if cl.get(s["id"]) in clusters and (i < 25 or CUE_RE.search(s["text"]))]
    lines = "\n".join(f"[{cl[s['id']]}] {s['text']}" for s in keep[:70])
    schema = {"type": "object", "properties": {"rationale": {"type": "string"},
                                               "advisor_cluster": {"type": "string", "enum": clusters}},
              "required": ["rationale", "advisor_cluster"]}
    obj = _ask(client, cache, "map_clusters", MAP_SYSTEM,
               f"Clusters: {', '.join(clusters)}\n\nTranscript:\n{lines}\n\n"
               'Return {"rationale": "<one sentence>", "advisor_cluster": "<cluster>"}.', schema, 300)
    adv = obj.get("advisor_cluster")
    if adv not in clusters:
        raise ValueError(f"invalid advisor_cluster {adv!r}")
    roles = {c: ("advisor" if c == adv else "customer") for c in clusters}
    return roles, str(obj.get("rationale") or "")


def label_segments_content_only(segments: list[dict], *, client, cache: DiskCache) -> dict[str, str]:
    """{segment_id: role} from text alone, windows of WINDOW segments overlapping by OVERLAP."""
    roles: dict[str, str] = {}
    step = WINDOW - OVERLAP
    for w0 in range(0, max(len(segments) - OVERLAP, 1), step):
        win = segments[w0: w0 + WINDOW]
        ids = [s["id"] for s in win]
        schema = {"type": "object", "properties": {"roles": {"type": "array", "items": {
            "type": "object", "properties": {"id": {"type": "string", "enum": ids},
                                             "role": {"type": "string", "enum": ["advisor", "customer", "unknown"]}},
            "required": ["id", "role"]}}}, "required": ["roles"]}
        lines = "\n".join(f"{s['id']}: {s['text']}" for s in win)
        obj = _ask(client, cache, "label_segments", LABEL_SYSTEM,
                   f"Lines:\n{lines}\n\nReturn {{\"roles\": [{{\"id\": \"<line id>\", \"role\": "
                   "\"advisor|customer|unknown\"}, ...]} with one entry per line, in order.", schema, 60 * len(win) + 200)
        for r in obj.get("roles") or []:
            if isinstance(r, dict) and r.get("id") in ids and r.get("role") in ("advisor", "customer", "unknown"):
                if roles.get(r["id"], "unknown") == "unknown":
                    roles[r["id"]] = r["role"]
    return {s["id"]: roles.get(s["id"], "unknown") for s in segments}
