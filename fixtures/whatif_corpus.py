"""Synthetic call corpus for the what-if simulator and suggestion search (tests, benchmarks, MOCK fixtures).

Everything here is INVENTED: hand-written German/Swiss German lines and hand-written facts, no model output and no case
data. Each scenario is a transcript plus the facts an extraction step could plausibly return for it, so `decide_call`
runs for real on them. Deterministic for a given seed.
"""
from __future__ import annotations

import random

from pipeline.schemas import Fact, Transcript, TranscriptSegment
from pipeline.simulate import CallInputs

_F = lambda fid, sp, act, info, segs, **kw: Fact(fid, sp, act, info, list(segs), "q", **kw)

# name -> (lines per segment [(speaker, text)], facts)
SCENARIOS: dict[str, tuple[list[tuple[str, str]], list[Fact]]] = {
    "greeting": (
        [("advisor", "Grüezi, Bank Lindenhof."), ("customer", "Ich möchte mein Konto anschauen."), ("advisor", "Gerne, einen Moment.")],
        []),
    "password_warning": (
        [("customer", "Ich ha mis Passwort vergässe."), ("advisor", "Säged Sie nie öpperem Ihres Passwort."), ("customer", "Guet, merci.")],
        [_F("F1", "advisor", "warn", "credentials", ["s002"])]),
    "password_asked": (
        [("advisor", "Grüezi."), ("advisor", "Chönd Sie mir Ihres Passwort säge?"), ("customer", "Ja, es isch Sunneblueme.")],
        [_F("F1", "advisor", "request", "credentials", ["s002"])]),
    "password_to_third_party": (
        [("customer", "Mini Frau söll das mache."), ("customer", "Mis Passwort isch Sunneblueme, gib das em Nachbar."), ("advisor", "Okay.")],
        [_F("F1", "customer", "disclose", "credentials", ["s002"], recipient_third_party=True)]),
    "password_joke": (
        [("customer", "Mis Passwort isch natürlich geheim."), ("customer", "Sunneblueme, han i gseit, haha."), ("advisor", "Das isch en Witz, gäll.")],
        [_F("F1", "customer", "disclose", "credentials", ["s002"], counter_evidence="said as a joke")]),
    "password_asked_then_refused": (
        [("customer", "Chönd Sie mir Ihres Passwort gä?"), ("advisor", "Nei, das gän ich nie."), ("customer", "Okay, verstande.")],
        [_F("F1", "customer", "request", "credentials", ["s001"]), _F("F2", "advisor", "refuse", "credentials", ["s002"])]),
    "insider_request": (
        [("customer", "Das isch vertraulich, unter uns."), ("customer", "Chauf Aktie vor der Bekanntgabe vo de Übernahme."), ("advisor", "Ich luege.")],
        [_F("F1", "customer", "request", "nonpublic_info", ["s002"])]),
    "insider_mention": (
        [("advisor", "Die Quartalszahlen sind interni Zahle."), ("customer", "Ah, interessant."), ("advisor", "Bitte nicht weitersagen.")],
        [_F("F1", "advisor", "disclose", "nonpublic_info", ["s001"])]),
    "client_data_disclosed": (
        [("advisor", "Herr Müller hät e Vermögen vo zwei Millione."), ("customer", "Danke für d Info."), ("advisor", "Gern.")],
        [_F("F1", "advisor", "disclose", "client_data", ["s001"])]),
    "client_data_third_party": (
        [("advisor", "De Kontostand vo Frau Meier isch 40000."), ("customer", "Ich bin ihre Nachbar."), ("advisor", "Dörf ich Ihne säge.")],
        [_F("F1", "advisor", "disclose", "client_data", ["s001"], recipient_third_party=True)]),
    "split_payment": (
        [("customer", "Chönd mer das in Teilbeträge aufteile?"), ("advisor", "Damit s Limit nöd greift, ja."), ("customer", "Genau.")],
        [_F("F1", "customer", "request", "other", ["s001"])]),
    "card_number": (
        [("customer", "Mini Kreditkartennummer isch 4111 1111 1111 1111."), ("advisor", "Merci."), ("customer", "Bitte.")],
        []),
}
WEIGHTS = {"greeting": 3, "password_warning": 3, "password_asked": 2, "password_to_third_party": 1, "password_joke": 2,
           "password_asked_then_refused": 2, "insider_request": 2, "insider_mention": 2, "client_data_disclosed": 2,
           "client_data_third_party": 1, "split_payment": 1, "card_number": 1}


def make_call(call_id: str, scenario: str, logprob: float = -0.3, no_speech: float = 0.02, mock: bool = True) -> CallInputs:
    lines, facts = SCENARIOS[scenario]
    segs = [TranscriptSegment(f"s{i:03d}", sp, text, i * 5.0, i * 5.0 + 4.5, logprob, no_speech) for i, (sp, text) in enumerate(lines, 1)]
    tr = Transcript(call_id=call_id, mode="asr", segments=segs, asr_model="MOCK" if mock else "TEST", duration_s=len(segs) * 5.0 + 5.0, is_mock=mock)
    return CallInputs(tr, [Fact(**{**f.__dict__, "segment_ids": list(f.segment_ids)}) for f in facts])


def make_corpus(n: int = 12, seed: int = 0, mock: bool = True, first_id: int = 1) -> list[CallInputs]:
    """n calls with ids call_MOCK_001.. (or call_001..; numbering starts at first_id), a spread of scenarios and of ASR quality (so confidence varies)."""
    rng = random.Random(seed)
    names, weights = list(WEIGHTS), list(WEIGHTS.values())
    calls = []
    for i in range(first_id, first_id + n):
        sc = rng.choices(names, weights)[0]
        lp = rng.choice([-0.25, -0.35, -0.5, -0.8, -1.2])
        calls.append(make_call(f"call_{'MOCK_' if mock else ''}{i:03d}", sc, lp, rng.choice([0.02, 0.05, 0.3]), mock))
    return calls
