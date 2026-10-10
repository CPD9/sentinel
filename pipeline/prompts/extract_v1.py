"""Fact-extraction prompt (step 4). Carries exactly the fields config/rules.yaml reads.

The prompt contains the numbered transcript only: no keyword hits, no call id, no file name, no label or level.
"""
from __future__ import annotations

from pipeline.schemas import FACT_ACTS, INFO_TYPES

PROMPT_VERSION = "extract-v1"

SYSTEM_PROMPT = """You extract facts from a phone call between a bank advisor and a customer, transcribed in Swiss \
German. You do NOT judge whether anything is a violation. You only record what was said.

The transcript lists one utterance per line as "[ID] (speaker) text". Every fact must cite the ids of the lines it \
rests on, copied exactly as written (same letters, same digits, same brackets removed), and must contain a short \
quote copied word for word from those lines.

Record a fact for every utterance where one of these happens:
- information of type "credentials" (password, PIN, one-time code, access secret), "nonpublic_info" (price-relevant \
information that is not public, e.g. an unannounced takeover) or "client_data" (details about a customer or another \
person, e.g. balance, address, relationship) is asked for, handed over, warned about, refused, discussed in the \
hypothetical, or quoted/read from somewhere;
- someone asks to leave out, hide or not write down a fact that the internal recipient should receive (use \
act "request", info_type "other", secrecy_cue true);
- someone asks to split a payment or transaction into parts to stay under a check, limit or approval (use act \
"request", info_type "other").
Also record the advisor's warnings and refusals and the customer's hypothetical or quoted mentions, because they \
weaken or excuse an earlier request: give them the same info_type as the thing they refer to.

Fields of one fact:
- speaker: "advisor" or "customer" (who spoke the quoted words).
- act: "request" (asks for or asks to do it), "disclose" (actually hands over or states it now), "warn" (cautions \
against it), "refuse" (declines), "hypothetical" (what-if, not actually happening), "quote" (reports or reads \
something said or written elsewhere, e.g. an expired value), "other".
- info_type: "credentials", "nonpublic_info", "client_data" or "other".
- recipient_third_party: true if the information goes to a person who is not the verified account holder or not \
entitled to it; false if it goes to the entitled person; null if unclear or not applicable.
- secrecy_cue: true if the speaker asks to keep it hidden or off the record; otherwise false.
- counter_evidence: one short sentence if the same call contains words that weaken this fact (a correction, a \
refusal, a statement that the value is expired), otherwise null.
- segment_ids: ids of the lines the fact rests on.
- quote: words copied exactly from those lines (a few words up to one sentence), in the original Swiss German.
- gloss_de: the quote rendered in Standard German.

Rules: never invent ids or words. Do not copy a fact from this instruction. If nothing relevant was said, return an \
empty list. Answer with ONE JSON object and nothing else: {"facts": [ ... ]}."""

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "speaker": {"type": "string", "enum": ["advisor", "customer", "unknown"]},
                "act": {"type": "string", "enum": list(FACT_ACTS)},
                "info_type": {"type": "string", "enum": list(INFO_TYPES)},
                "recipient_third_party": {"type": ["boolean", "null"]},
                "secrecy_cue": {"type": ["boolean", "null"]},
                "counter_evidence": {"type": ["string", "null"]},
                "segment_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "quote": {"type": "string"},
                "gloss_de": {"type": ["string", "null"]},
            },
            "required": ["speaker", "act", "info_type", "recipient_third_party", "secrecy_cue",
                         "counter_evidence", "segment_ids", "quote", "gloss_de"],
        }},
    },
    "required": ["facts"],
}


def user_message(segments: list[dict]) -> str:
    """segments: {id, speaker, text}. Ids are the transcript's own (neutral) ids."""
    return "Transcript:\n" + "\n".join(f"[{s['id']}] ({s['speaker']}) {s['text']}" for s in segments)
