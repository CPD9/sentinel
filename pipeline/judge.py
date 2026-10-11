"""Direct judge (strategy S4) for speech-recognition transcripts: one LLM prompt per call -> verdict, risk, citations.

Why (T5b, 11 Oct 2026): the facts -> rules risk ranks calls below chance (AUC 0.37 in ASR mode, 0.41 on reference
scripts) while the one-prompt judge was the only strategy above chance on reference scripts (AUC 0.64). This module
runs that judge on ASR transcripts (roles unknown, Standard-German spelling, recognition errors) and checks every
citation with the same evidence validator as the facts (segment id exists, quote found in the cited segment).

    judge_call(transcript, client=None, cache=None) -> JudgeResult

Cached by content hash + model + prompt version (artifacts/cache/judge). Temperature 0 and a strict JSON schema.
An unusable answer raises JudgeError (the caller records a stage error; never a silent no_alert).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from pipeline import llm
from pipeline.llm import DiskCache, extraction_cache_key
from pipeline.schemas import CRITERIA, DECISIONS, Fact, Transcript
from pipeline.validate import validate_facts

CACHE_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "cache" / "judge"
MAX_OUTPUT_TOKENS = 700
PROMPT_VERSION = "judge-asr-v1"

SYSTEM_PROMPT = """You are a compliance reviewer for a Swiss bank. You read the transcript of one phone call \
between a bank advisor and a customer and decide whether compliance must be alerted. The call was spoken in Swiss \
German and transcribed by automatic speech recognition: the text is mostly spelled in Standard German and contains \
recognition errors. Who spoke is NOT marked: every line says "(speaker)"; infer from the content whether a line is the \
advisor (works for the bank) or the customer.

Criteria (the only reasons for an alarm):
- insider_trading: the customer requests a trade of their own BECAUSE of nonpublic, price-relevant \
information they hold (e.g. an unannounced takeover from an insider). Execution is not required.
- credential_sharing: someone actually discloses a currently active access secret (password, PIN, \
one-time code). Mentioning, refusing, or reading an expired value is not disclosure of an active secret.
- third_party_disclosure: the advisor actually reveals protected details about another person after it \
was clear the caller is not authorised. Merely asking, or refusing, is not disclosure.
- documentation_concealment: an intentional request to hide a relevant fact from the internal party who \
must receive it. Correcting a mistake is fine.
- control_evasion: a request to split a payment or transaction into connected parts expressly to avoid a \
stated internal check or approval process.
- payment_card_data: a full number is read out; classify what it is. Digits alone never justify an alarm.

Decisions:
- "alarm": the call clearly meets one criterion.
- "review": a criterion might be met, but a decisive fact is missing or ambiguous, so a human must decide.
- "no_alert": no criterion is met (including calls where a risky topic is raised and correctly refused).

Answer with ONE JSON object and nothing else:
{"decision": "alarm" | "review" | "no_alert",
 "criterion": one of the criterion names above, or "none",
 "risk": number between 0 and 1 (how likely compliance must act),
 "reason": one or two sentences,
 "evidence": [{"segment_id": "S0012", "speaker": "advisor" | "customer", "quote": "exact words copied from that line"}]}
Cite the lines that justify the decision (empty list for no_alert), with the id exactly as written between the \
brackets. Quotes must be copied verbatim from the cited line, at most 15 words."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "criterion": {"type": "string", "enum": [c for c in CRITERIA if c != "other"] + ["none"]},
        "risk": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "maxItems": 6, "items": {
            "type": "object",
            "properties": {"segment_id": {"type": "string"},
                           "speaker": {"type": "string", "enum": ["advisor", "customer"]},
                           "quote": {"type": "string"}},
            "required": ["segment_id", "speaker", "quote"]}},
    },
    "required": ["decision", "criterion", "risk", "reason", "evidence"],
}
PROMPT_VERSION_FULL = PROMPT_VERSION + "+" + hashlib.sha256(
    json.dumps([SYSTEM_PROMPT, RESPONSE_SCHEMA, MAX_OUTPUT_TOKENS], sort_keys=True).encode()).hexdigest()[:8]


class JudgeError(RuntimeError):
    pass


@dataclass
class JudgeResult:
    decision: str
    criterion: str
    risk: float
    reason: str
    citations: list[Fact] = field(default_factory=list)     # validated: .valid / .drop_reason set
    cached: bool = False
    metrics: list[dict] = field(default_factory=list)

    @property
    def valid_citations(self) -> list[Fact]:
        return [c for c in self.citations if c.valid]

    def to_dict(self) -> dict:
        return {"decision": self.decision, "criterion": self.criterion, "risk": self.risk, "reason": self.reason,
                "citations": [c.__dict__ for c in self.citations], "version": PROMPT_VERSION_FULL}


def user_message(transcript: Transcript) -> str:
    lines = [f"[{s.id}] ({'speaker' if s.speaker == 'unknown' else s.speaker}) {s.text}" for s in transcript.segments]
    return "Transcript:\n" + "\n".join(lines)


def parse(text: str) -> dict:
    t = text.strip()
    try:
        obj = json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise JudgeError("no JSON object in the judge's answer") from None
        try:
            obj = json.loads(t[a:b + 1])
        except ValueError as e:
            raise JudgeError(f"invalid JSON from the judge: {e}") from None
    if not isinstance(obj, dict) or obj.get("decision") not in DECISIONS:
        raise JudgeError(f"judge answer without a valid decision: {str(obj)[:200]}")
    return obj


def judge_call(transcript: Transcript, *, client=None, cache: DiskCache | None = None) -> JudgeResult:
    client = client or llm.get_client()
    if client.model_revision is None:
        client.probe()
    cache = cache or DiskCache(CACHE_DIR)
    segs = [{"id": s.id, "speaker": s.speaker, "text": s.text} for s in transcript.segments]
    key = extraction_cache_key(segs, client.model, client.model_revision, PROMPT_VERSION_FULL, provider=client.spec.name)
    hit = cache.get(key)
    if hit is not None:
        text, metrics, cached = hit["response"], hit["metrics"], True
    else:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_message(transcript)}]
        text, m = client.chat_with_metrics(messages, temperature=0.0, max_tokens=MAX_OUTPUT_TOKENS,
                                           json_schema=RESPONSE_SCHEMA)
        metrics, cached = [m.to_dict()], False
        parse(text)                                   # never cache an unusable answer
        cache.put(key, {"response": text, "metrics": metrics, "prompt_version": PROMPT_VERSION_FULL,
                        "provider": client.spec.name, "model": client.model, "revision": client.model_revision})
    obj = parse(text)
    risk = obj.get("risk")
    risk = min(max(float(risk), 0.0), 1.0) if isinstance(risk, (int, float)) and not isinstance(risk, bool) else \
        {"alarm": 0.9, "review": 0.5, "no_alert": 0.1}[obj["decision"]]
    crit = obj.get("criterion") if obj.get("criterion") in CRITERIA else "other"
    cites = []
    for i, e in enumerate(obj.get("evidence") or []):
        if not isinstance(e, dict) or not e.get("segment_id"):
            continue
        sp = e.get("speaker") if e.get("speaker") in ("advisor", "customer") else "unknown"
        cites.append(Fact(f"j{i + 1:03d}", sp, "other", "other", [str(e["segment_id"])], str(e.get("quote") or "")))
    return JudgeResult(obj["decision"], crit, round(risk, 4), str(obj.get("reason") or ""),
                       validate_facts(cites, transcript), cached, metrics)
