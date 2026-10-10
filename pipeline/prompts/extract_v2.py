"""Fact-extraction prompt v2 (step 4), written after the v1 runs on dev.

What v1 showed (dev n=28, reference transcripts): Apertus cited zero-stripped ids ("T12" for "T012", 16 dropped facts),
wrote one 8-segment `nonpublic_info` request that fired insider_trading on four calls, and extracted only 3 facts per call;
Llama-3.3-70B marked ordinary statements as `client_data`. v2 therefore names the id format and shows it, caps a fact at
3 adjacent segments (also in the JSON schema and checked in pipeline/extract.py), asks for one fact per utterance walking
the call in order, and tightens what counts as credentials / nonpublic_info / client_data. Same fields as v1.

The prompt contains the numbered transcript only: no keyword hits, no call id, no file name, no label or level.
"""
from __future__ import annotations

import copy

from pipeline.prompts.extract_v1 import FACT_SCHEMA as _V1_SCHEMA

PROMPT_VERSION = "extract-v2"
MAX_SEGMENT_IDS = 3
WINDOW_TOKENS = 1400          # est. transcript tokens per window: v2 answers one fact per relevant utterance, so long windows overflow the budget
MAX_OUTPUT_TOKENS = 3000      # v2 lists one fact per utterance; 1500 truncated the JSON on long calls (12 of 28 dev calls)

SYSTEM_PROMPT = """You extract facts from a phone call between a bank advisor and a customer, transcribed in Swiss \
German. You do NOT judge whether anything is a violation. You only record what was said, utterance by utterance.

The transcript lists one utterance per line as "[ID] (speaker) text". Ids are padded with leading zeros, for example \
[T012] or [S0012], never T12. Copy ids exactly as written between the brackets.

Go through the transcript from the first line to the last. Write a fact only for an utterance that matches one of \
the cases below, one fact per such utterance. Greetings, small talk, questions about procedure and plain confirmations \
get no fact:
- "credentials": a secret that gives access (password, PIN, one-time or SMS code, security answer) is asked for, \
handed over (spoken or read out digit by digit), warned about, refused, or discussed in the hypothetical. A card or \
account number is not a credential: use info_type "other".
- "nonpublic_info": price-relevant information about a company that is not public yet (for example an unannounced \
takeover or results before publication) is mentioned, or someone asks to trade because of it.
- "client_data": personal details of a customer or of another person (balance, address, family, account details) \
are asked for, handed over, warned about or refused. Business processes, documents, appointments and the caller's own \
plans are not client_data.
- Someone asks to leave out, hide or not write down a fact that the internal recipient should receive: act \
"request", info_type "other", secrecy_cue true.
- Someone asks to split a payment or transaction into parts to stay under a check, limit or approval: act \
"request", info_type "other".
Also record the advisor's warnings and refusals and the customer's hypothetical or quoted mentions, because they \
weaken or excuse an earlier request: give them the same info_type as the thing they refer to.

Fields of one fact:
- speaker: "advisor" or "customer" (who spoke the quoted words).
- act: "request" (asks for or asks to do it), "disclose" (actually hands over or states it now), "warn" (cautions \
against it), "refuse" (declines), "hypothetical" (what-if, not actually happening), "quote" (reports or reads \
something said or written elsewhere, for example an expired value), "other".
- info_type: "credentials", "nonpublic_info", "client_data" or "other".
- recipient_third_party: true if the information goes to a person who is not the verified account holder or not \
entitled to it; false if it goes to the entitled person; null if unclear or not applicable.
- secrecy_cue: true if the speaker asks to keep it hidden or off the record; otherwise false.
- counter_evidence: one short sentence if the same call contains words that weaken this fact (a correction, a \
refusal, a statement that the value is expired), otherwise null.
- segment_ids: the id of the line that was spoken. Use up to 3 adjacent lines (directly one after the other) only \
when the statement really continues over them. Never a range, never a long list, never lines far apart: if several \
separate utterances matter, write one fact per utterance.
- quote: the shortest excerpt (at most 15 words) copied exactly from one of the cited lines that shows the point, in \
the original Swiss German. Never the whole utterance when it is longer.
- gloss_de: the quote rendered in Standard German.

Rules: never invent ids or words. If nothing relevant was said, return an empty list. Answer with ONE JSON object \
and nothing else: {"facts": [ ... ]}.

Format example (invented, not from this call):
[T021] (advisor) Bitte säged Sie mir nöd Ihres Passwort.
[T022] (customer) Mis Passwort isch Rosenstock.
{"facts": [{"speaker": "advisor", "act": "warn", "info_type": "credentials", "recipient_third_party": null, \
"secrecy_cue": false, "counter_evidence": null, "segment_ids": ["T021"], "quote": "Bitte säged Sie mir nöd Ihres \
Passwort", "gloss_de": "Bitte sagen Sie mir nicht Ihr Passwort"}, {"speaker": "customer", "act": "disclose", \
"info_type": "credentials", "recipient_third_party": false, "secrecy_cue": false, "counter_evidence": null, \
"segment_ids": ["T022"], "quote": "Mis Passwort isch Rosenstock", "gloss_de": "Mein Passwort ist Rosenstock"}]}"""

FACT_SCHEMA = copy.deepcopy(_V1_SCHEMA)
FACT_SCHEMA["properties"]["facts"]["items"]["properties"]["segment_ids"]["maxItems"] = MAX_SEGMENT_IDS


def user_message(segments: list[dict]) -> str:
    """segments: {id, speaker, text}. Ids are the transcript's own (neutral) ids."""
    first, last = (segments[0]["id"], segments[-1]["id"]) if segments else ("", "")
    return (f"Segment ids run from [{first}] to [{last}]. Copy them exactly, with every leading zero.\n\nTranscript:\n"
            + "\n".join(f"[{s['id']}] ({s['speaker']}) {s['text']}" for s in segments))
