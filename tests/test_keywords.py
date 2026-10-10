"""Step 3: fuzzy keyword matching (synthetic transcripts, real config/keywords.json)."""
import copy
import json
from pathlib import Path

import pytest

from pipeline.keywords import ConfigError, find_hits, load_keywords, parse_keywords
from pipeline.schemas import Transcript, TranscriptSegment

CFG = load_keywords()


def tr(*texts):
    segs = [TranscriptSegment(id=f"s{i:03d}", speaker="unknown", text=t, start_s=float(i), end_s=i + 0.9)
            for i, t in enumerate(texts, 1)]
    return Transcript(call_id="call_T", mode="asr", segments=segs)


def terms(hits):
    return [(h.family, h.term, h.segment_id) for h in hits]


def test_exact_and_fuzzy_hit():
    hits = find_hits(tr("Ich ha mis Passwort vergässe", "Mis Passwoort isch alt"), CFG)
    assert terms(hits) == [("access", "Passwort", "s001"), ("access", "Passwort", "s002")]
    assert hits[0].score == 1.0 and 0.85 <= hits[1].score < 1.0
    assert hits[1].matched_text == "Passwoort"
    assert [h.hit_id for h in hits] == ["H1", "H2"]


def test_no_partial_word_hit():
    assert find_hits(tr("Das Passwortmanager Zeug"), CFG) == []


def test_short_terms_are_exact_only():
    assert terms(find_hits(tr("Mini PIN isch 1234"), CFG)) == [("access", "PIN", "s001")]
    assert find_hits(tr("Pina Colada"), CFG) == []


def test_swiss_german_variant_maps_to_canonical_term():
    (h,) = find_hits(tr("Das isch nöd öffentlich"), CFG)
    assert (h.family, h.term, h.matched_text) == ("trade", "nicht öffentlich", "nöd öffentlich")


def test_multiword_term_and_punctuation():
    (h,) = find_hits(tr("Wir könnten das aufteilen, oder?"), CFG)
    assert (h.family, h.term, h.matched_text) == ("splitting", "aufteilen", "aufteilen")


def test_deterministic():
    t = tr("Passwort und Kreditkarte", "PIN")
    assert find_hits(t, CFG) == find_hits(t, CFG)


def test_bad_config_rejected():
    d = json.loads((Path(__file__).parents[1] / "config" / "keywords.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(d)
    bad["families"]["gossip"] = {"terms": ["x"]}
    bad["fuzzy_threshold"] = 3
    bad["families"]["access"]["variants"]["nope"] = ["x"]
    with pytest.raises(ConfigError) as e:
        parse_keywords(bad)
    assert len(e.value.errors) == 3
