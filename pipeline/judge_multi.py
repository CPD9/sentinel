"""Multi-check judge: the direct judge run once per criterion, each with a focused zero-shot prompt.

Same criterion definitions, citation rules, JSON discipline and evidence validator as pipeline/judge.py (one general
verdict). Each check answers only "is THIS criterion met in this call?". The call's risk is the maximum over the
checks; decision, criterion, reason and citations come from the top check (ties: the first criterion in
schemas.CRITERIA order). Zero-shot: nothing is fitted on labels.

    judge_call_multi(transcript, client=None, cache=None) -> judge.JudgeResult   (+ .checks: per-criterion results)
"""
from __future__ import annotations

import hashlib
import json
import re

from pipeline import judge, llm
from pipeline.llm import DiskCache, extraction_cache_key
from pipeline.schemas import CRITERIA, DECISIONS, Fact, Transcript
from pipeline.validate import validate_facts

PROMPT_VERSION = "judge-asr-mc-v1"
CHECKED = tuple(c for c in CRITERIA if c != "other")

# The criterion lines of the single judge's prompt, so both judges share one definition per criterion.
DEFINITIONS = {m.group(1): " ".join(m.group(2).split())
               for m in re.finditer(r"^- (\w+): (.+?)(?=^- \w+:|^\nDecisions:)", judge.SYSTEM_PROMPT, re.M | re.S)}

_INTRO = judge.SYSTEM_PROMPT.split("Criteria (the only reasons for an alarm):")[0]

CHECK_PROMPT = _INTRO + """You check exactly ONE criterion in this call and ignore every other kind of problem:

{name}: {definition}

Decisions:
- "alarm": the call clearly meets THIS criterion.
- "review": THIS criterion might be met, but a decisive fact is missing or ambiguous, so a human must decide.
- "no_alert": THIS criterion is not met (including calls where the topic is raised and correctly refused).

Answer with ONE JSON object and nothing else:
{{"decision": "alarm" | "review" | "no_alert",
 "risk": number between 0 and 1 (how likely compliance must act on THIS criterion),
 "reason": one or two sentences,
 "evidence": [{{"segment_id": "S0012", "speaker": "advisor" | "customer", "quote": "exact words copied from that line"}}]}}
Cite the lines that justify the decision (empty list for no_alert), with the id exactly as written between the \
brackets. Quotes must be copied verbatim from the cited line, at most 15 words."""

CHECK_SCHEMA = {
    "type": "object",
    "properties": {k: v for k, v in judge.RESPONSE_SCHEMA["properties"].items() if k != "criterion"},
    "required": ["decision", "risk", "reason", "evidence"],
}
PROMPT_VERSION_FULL = PROMPT_VERSION + "+" + hashlib.sha256(json.dumps(
    [CHECK_PROMPT, sorted(DEFINITIONS.items()), CHECK_SCHEMA, judge.MAX_OUTPUT_TOKENS], sort_keys=True).encode()).hexdigest()[:8]


def check_prompt(criterion: str) -> str:
    return CHECK_PROMPT.format(name=criterion, definition=DEFINITIONS[criterion])


def _one(transcript: Transcript, criterion: str, client, cache: DiskCache) -> judge.JudgeResult:
    segs = [{"id": s.id, "speaker": s.speaker, "text": s.text} for s in transcript.segments]
    key = extraction_cache_key(segs, client.model, client.model_revision, f"{PROMPT_VERSION_FULL}:{criterion}",
                               provider=client.spec.name)
    hit = cache.get(key)
    if hit is not None:
        text, metrics, cached = hit["response"], hit["metrics"], True
    else:
        messages = [{"role": "system", "content": check_prompt(criterion)},
                    {"role": "user", "content": judge.user_message(transcript)}]
        text, m = client.chat_with_metrics(messages, temperature=0.0, max_tokens=judge.MAX_OUTPUT_TOKENS,
                                           json_schema=CHECK_SCHEMA)
        metrics, cached = [m.to_dict()], False
        judge.parse(text)
        cache.put(key, {"response": text, "metrics": metrics, "prompt_version": f"{PROMPT_VERSION_FULL}:{criterion}",
                        "provider": client.spec.name, "model": client.model, "revision": client.model_revision})
    obj = judge.parse(text)
    risk = obj.get("risk")
    risk = min(max(float(risk), 0.0), 1.0) if isinstance(risk, (int, float)) and not isinstance(risk, bool) else \
        {"alarm": 0.9, "review": 0.5, "no_alert": 0.1}[obj["decision"]]
    if obj["decision"] == "no_alert":
        risk = min(risk, 0.1)               # a check that says "not met" cannot carry a review-level risk
    cites = []
    for i, e in enumerate(obj.get("evidence") or []):
        if isinstance(e, dict) and e.get("segment_id"):
            sp = e.get("speaker") if e.get("speaker") in ("advisor", "customer") else "unknown"
            cites.append(Fact(f"{criterion[:2]}{i + 1:02d}", sp, "other", "other", [str(e["segment_id"])],
                              str(e.get("quote") or "")))
    return judge.JudgeResult(obj["decision"], criterion, round(risk, 4), str(obj.get("reason") or ""),
                             validate_facts(cites, transcript), cached, metrics)


def judge_call_multi(transcript: Transcript, *, client=None, cache: DiskCache | None = None) -> judge.JudgeResult:
    client = client or llm.get_client()
    if client.model_revision is None:
        client.probe()
    cache = cache or DiskCache(judge.CACHE_DIR)
    checks, failed = [], []
    for c in CHECKED:
        try:
            checks.append(_one(transcript, c, client, cache))
        except judge.JudgeError as e:        # an unusable check is a review for that criterion, never a silent no
            failed.append(c)
            checks.append(judge.JudgeResult("review", c, 0.5, f"check failed, human review: {e}"[:300], []))
    rank = {d: i for i, d in enumerate(DECISIONS)}            # alarm < review < no_alert
    top = min(checks, key=lambda r: (-r.risk, rank[r.decision], CHECKED.index(r.criterion)))
    out = judge.JudgeResult(top.decision, top.criterion, top.risk, top.reason, top.citations,
                            all(c.cached for c in checks), [m for c in checks for m in c.metrics])
    out.checks, out.failed_checks = checks, failed
    return out
