"""Evidence validator (step 5): facts are flagged, never deleted."""
from dataclasses import replace

from pipeline.schemas import Fact, Transcript, TranscriptSegment
from pipeline.validate import (NO_CITATION, R_EMPTY, R_NO_CITATION, R_QUOTE, R_SPEAKER, R_UNKNOWN_ID, reason_key,
                               validate_facts)

TR = Transcript("call_x", "reference", [
    TranscriptSegment("T001", "advisor", "Grüezi, Bank Lindenhof."),
    TranscriptSegment("T002", "customer", "Mis Passwort isch Sunneblueme, händ Sie das?"),
    TranscriptSegment("T003", "advisor", "Das dörf ich nöd ufschriibe."),
])


def fact(**kw):
    base = dict(fact_id="f001", speaker="customer", act="disclose", info_type="credentials", segment_ids=["T002"],
                quote="Mis Passwort isch Sunneblueme")
    return Fact(**{**base, **kw})


def one(**kw):
    (f,) = validate_facts([fact(**kw)], TR)
    return f


def test_good_fact_stays_valid():
    f = one()
    assert f.valid and f.drop_reason is None


def test_case_insensitive_id_resolves_and_is_canonicalised():
    f = one(segment_ids=["t002"])
    assert f.valid and f.segment_ids == ["T002"]


def test_brackets_around_id_resolve():
    assert one(segment_ids=["[T002]"]).valid


def test_numeric_guessing_is_not_allowed():
    f = one(segment_ids=["T2"])
    assert not f.valid and f.drop_reason.startswith(R_UNKNOWN_ID) and "T2" in f.drop_reason


def test_hallucinated_id_among_real_ones_drops():
    assert not one(segment_ids=["T002", "T099"]).valid


def test_empty_quote():
    assert one(quote="  ").drop_reason == R_EMPTY


def test_no_citation():
    assert one(segment_ids=[NO_CITATION]).drop_reason == R_NO_CITATION


def test_wrong_quote():
    f = one(quote="Ich überwiise hundert Franke uf s Konto vo minere Schwöschter")
    assert not f.valid and f.drop_reason.startswith(R_QUOTE)


def test_small_transcription_variation_in_quote_is_tolerated():
    assert one(quote="mis passwort ist sunneblume").valid


def test_wrong_speaker():
    f = one(speaker="advisor")
    assert not f.valid and f.drop_reason.startswith(R_SPEAKER)


def test_unknown_segment_speaker_is_not_a_mismatch():
    tr = replace(TR, segments=[TranscriptSegment("T002", "unknown", "Mis Passwort isch Sunneblueme")])
    assert validate_facts([fact()], tr)[0].valid


def test_nothing_is_deleted_and_dropped_keep_first_reason():
    pre = fact(fact_id="f002", valid=False, drop_reason="invalid field: act 'x'")
    out = validate_facts([fact(), pre, fact(quote="")], TR)
    assert len(out) == 3 and out[1].drop_reason == "invalid field: act 'x'"


def test_reason_keys_are_stable():
    assert reason_key("unknown segment id: T9") == R_UNKNOWN_ID
    assert reason_key("quote not in cited segments (0.12)") == R_QUOTE
    assert reason_key(None) is None
