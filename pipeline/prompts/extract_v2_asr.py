"""Fact-extraction prompt v2-asr: prompt v2 for speech-recognition transcripts without speaker roles.

Why: on ASR transcripts every segment's speaker is unknown (no diarization). Shown as "(unknown)", Apertus answered
{"facts": []} for every window; shown as "(speaker)" with the v2 text it found about a tenth of the facts it finds on
reference scripts (77 vs 673 on dev + Testset_30), because v2 says "Swiss German" and shows advisor/customer-labelled
lines. v2-asr says the roles are unknown, asks the model to infer advisor vs customer per fact from the content and
to write the role into the fact, notes that the text is Standard-German-spelled ASR output with recognition errors,
and shows an example with unlabelled lines. Same fields, schema, window and output budgets as v2, so the two are
comparable. Selected automatically by pipeline/extract.py when every segment's speaker is unknown; reference
transcripts keep v2 unchanged.
"""
from __future__ import annotations

from pipeline.prompts import extract_v2 as _v2
from pipeline.prompts.extract_v2 import FACT_SCHEMA, MAX_OUTPUT_TOKENS, MAX_SEGMENT_IDS, WINDOW_TOKENS  # noqa: F401

PROMPT_VERSION = "extract-v2-asr"

_INTRO_V2 = """You extract facts from a phone call between a bank advisor and a customer, transcribed in Swiss \
German. You do NOT judge whether anything is a violation. You only record what was said, utterance by utterance.

The transcript lists one utterance per line as "[ID] (speaker) text"."""

_INTRO = """You extract facts from a phone call between a bank advisor and a customer. The call was spoken in Swiss \
German and transcribed by automatic speech recognition: the text is mostly spelled in Standard German and contains \
recognition errors (misheard names, numbers and words). You do NOT judge whether anything is a violation. You only \
record what was said, utterance by utterance.

The transcript lists one utterance per line as "[ID] (speaker) text". Who spoke is NOT known: every line says \
"(speaker)", and consecutive lines may come from the same person or from the other one. For every fact, decide from \
the content who said the quoted words: the ADVISOR works for the bank (names the bank or service, verifies identity, \
explains procedures, asks for or offers information, warns); the CUSTOMER calls about their own account, payment or \
problem and gives their own data. Write that role ("advisor" or "customer") in the fact's speaker field, never \
"speaker" and never "unknown"."""

_FIELD_V2 = '- speaker: "advisor" or "customer" (who spoke the quoted words).'
_FIELD = ('- speaker: "advisor" or "customer": who spoke the quoted words, inferred from the content (the lines carry '
          'no role).')

_QUOTE_V2 = "the original Swiss German."
_QUOTE = "the transcript's own words."

_EXAMPLE_V2 = """[T021] (advisor) Bitte säged Sie mir nöd Ihres Passwort.
[T022] (customer) Mis Passwort isch Rosenstock."""
_EXAMPLE = """[S0021] (speaker) Bitte sagen Sie mir nicht Ihr Passwort.
[S0022] (speaker) Mein Passwort ist Rosenstock."""

def _build() -> str:
    s = _v2.SYSTEM_PROMPT
    for old, new in ((_INTRO_V2, _INTRO), (_FIELD_V2, _FIELD), (_QUOTE_V2, _QUOTE), (_EXAMPLE_V2, _EXAMPLE)):
        if old not in s:
            raise RuntimeError(f"extract_v2 changed; v2-asr cannot patch: {old[:50]!r}")
        s = s.replace(old, new)
    s = s.replace('"segment_ids": ["T021"], "quote": "Bitte säged Sie mir nöd Ihres Passwort"',
                  '"segment_ids": ["S0021"], "quote": "Bitte sagen Sie mir nicht Ihr Passwort"')
    s = s.replace('"segment_ids": ["T022"], "quote": "Mis Passwort isch Rosenstock"',
                  '"segment_ids": ["S0022"], "quote": "Mein Passwort ist Rosenstock"')
    return s


SYSTEM_PROMPT = _build()


def user_message(segments: list[dict]) -> str:
    """Same as v2 (the caller shows unknown speakers as "(speaker)")."""
    return _v2.user_message(segments)
