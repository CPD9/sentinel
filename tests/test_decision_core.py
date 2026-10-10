"""Steps 3 + 6-8: rules, confidence gate and decision, on synthetic hand-written facts (no data/ needed)."""
import copy
import itertools
import json
from pathlib import Path

import pytest
import yaml

from pipeline import llm
from pipeline.decide import Config, config_from_dicts, decide_call, load_config, with_thresholds
from pipeline.keywords import ConfigError, find_hits
from pipeline.rules import parse_rules
from pipeline.schemas import (AnalysisArtifact, DecisionTrace, Fact, StageError, Transcript, TranscriptSegment)

CONFIG_DIR = Path(__file__).parents[1] / "config"
CFG = load_config()

TEXTS = {
    "s001": ("advisor", "Grüezi, Bank Lindenhof."),
    "s002": ("customer", "Ich ha mis Passwort vergässe."),
    "s003": ("advisor", "Säged Sie nie öpperem Ihres Passwort."),
    "s004": ("customer", "Mis Passwort isch Sunneblueme."),
    "s005": ("advisor", "Merci, ich schicke en Link."),
    "s006": ("customer", "Guet, uf Widerluege."),
}


def transcript(lp=-0.2, nsp=0.02, texts=None):
    segs = [TranscriptSegment(i, sp, t, float(n), n + 0.9, lp, nsp) for n, (i, (sp, t)) in enumerate((texts or TEXTS).items())]
    return Transcript(call_id="call_T", mode="asr", segments=segs, asr_model="TEST")


def fact(fid, speaker, act, info, segs, **kw):
    return Fact(fid, speaker, act, info, list(segs), "q", **kw)


def raw():
    return (json.loads((CONFIG_DIR / "keywords.json").read_text(encoding="utf-8")),
            yaml.safe_load((CONFIG_DIR / "rules.yaml").read_text(encoding="utf-8")),
            json.loads((CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8")))


def run(facts, t=None, config=CFG, an=None, **kw):
    trace = decide_call(t or transcript(), facts, an, config, **kw)
    assert DecisionTrace.validate(trace.to_dict()) == []
    return trace


def noisy_analysis(score=0.0):
    ax = {"x": {"label": "time", "unit": "s"}, "value": {"label": "q", "unit": "score 0-1"}}
    return AnalysisArtifact.from_dict({"call_id": "call_T", "duration_s": 10.0, "sample_rate": 16000,
                                       "audio_quality": {"call_snr_db": 2.0, "call_score": score, "segments": [], "axes": ax}})


WARN = lambda: fact("F1", "advisor", "warn", "credentials", ["s003"])
REQUEST = lambda: fact("F1", "advisor", "request", "credentials", ["s003"])
DISCLOSE_3P = lambda: fact("F1", "customer", "disclose", "credentials", ["s004"], recipient_third_party=True)
DISCLOSE = lambda: fact("F2", "customer", "disclose", "credentials", ["s004"])

# --------------------------------------------------------------------------- the required scenarios


def test_advisor_warns_never_to_share_password_is_no_alert():
    t = run([WARN()])
    assert (t.decision, t.decision_path) == ("no_alert", "no_alert")
    assert not any(r.fired for r in t.rules)


def test_asking_for_a_password_is_an_alarm():
    t = run([REQUEST()])
    assert (t.decision, t.decision_path) == ("alarm", "alarm")
    (r,) = [r for r in t.rules if r.criterion == "credential_sharing"]
    assert r.fired and r.fact_ids == ["F1"] and r.keyword_hit_ids


def test_passing_credentials_to_a_third_party_is_an_alarm():
    t = run([DISCLOSE_3P()])
    assert t.decision == "alarm" and t.risk_score >= 0.95


def test_contradictory_facts_on_same_criterion_are_review():
    t = run([DISCLOSE(), fact("F3", "customer", "refuse", "credentials", ["s004"])])
    assert (t.decision, t.decision_path) == ("review", "contradictory_evidence")


@pytest.mark.parametrize("facts", [[DISCLOSE_3P()], None])
def test_failed_stage_is_review_never_alarm(facts):
    t = run(facts, stage_errors=[StageError("extract", "LLM unreachable")] if facts else None)
    assert (t.decision, t.decision_path) == ("review", "stage_error")


def test_failed_stage_with_no_findings_is_not_no_alert():
    assert run([], stage_errors=[StageError("asr", "boom")]).decision == "review"


def test_low_confidence_with_high_risk_rule_is_review_not_alarm():
    junk = [fact(f"J{i}", "advisor", "other", "other", ["s001"], valid=False, drop_reason="no match") for i in range(2)]
    t = run([DISCLOSE_3P(), *junk], t=transcript(lp=-1.4, nsp=0.5), an=noisy_analysis(0.0))
    assert t.confidence < t.thresholds.confidence_gate
    assert t.risk_score >= t.thresholds.alarm
    assert (t.decision, t.decision_path) == ("review", "low_confidence")


def test_keyword_only_hit_never_alarms():
    t = run([])
    assert t.keyword_hits and t.decision != "alarm"
    kws, rules, th = raw()
    rules["defaults"]["keyword_only_risk"] = 1.0
    for r in rules["rules"]:
        r.pop("keyword_only_risk", None)
        r.pop("max_risk", None)
    stress = config_from_dicts(kws, rules, th)
    t = run([], config=stress)
    assert t.risk_score == 1.0 and t.decision == "review" and t.decision_path == "missing_evidence"
    assert run([], config=with_thresholds(stress, alarm=0.2, review=0.1)).decision == "review"


def scenarios():
    return {
        "warn": [WARN()], "request": [REQUEST()], "disclose_3p": [DISCLOSE_3P()], "none": [],
        "request_then_refuse": [fact("F1", "customer", "request", "credentials", ["s002"]),
                                fact("F2", "advisor", "refuse", "credentials", ["s003"])],
        "refuse_then_disclose": [fact("F1", "advisor", "refuse", "credentials", ["s003"]), DISCLOSE()],
        "contradiction": [DISCLOSE(), fact("F3", "customer", "quote", "credentials", ["s004"])],
        "dropped": [fact("F1", "customer", "disclose", "credentials", ["s004"], valid=False, drop_reason="x")],
    }


@pytest.mark.parametrize("name", list(scenarios()))
def test_alarm_threshold_is_monotonic(name):
    grid = [0.45, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]
    for gate in (0.3, 0.5, 0.9):
        alarms = [run(scenarios()[name], config=with_thresholds(CFG, alarm=a, confidence_gate=gate)).decision == "alarm"
                  for a in grid]
        # once a higher threshold stops alarming, an even higher one must not start again
        assert alarms == sorted(alarms, reverse=True), (name, gate, alarms)


def test_raising_alarm_threshold_never_creates_an_alarm_from_any_other_decision():
    for name, a_lo, a_hi in itertools.product(scenarios(), (0.5, 0.7), (0.8, 0.95)):
        lo = run(scenarios()[name], config=with_thresholds(CFG, alarm=a_lo)).decision
        hi = run(scenarios()[name], config=with_thresholds(CFG, alarm=a_hi)).decision
        assert not (lo != "alarm" and hi == "alarm"), name


def test_editing_keywords_json_does_not_change_the_llm_cache_key():
    t = transcript()
    segs = [{"id": s.id, "speaker": s.speaker, "text": s.text} for s in t.segments]
    key = llm.extraction_cache_key(segs, "swiss-ai/Apertus-v1.5-8B", "rev1", "prompt-v1", provider="apertus_aws")
    kws, rules, th = raw()
    before = find_hits(t, config_from_dicts(kws, rules, th).keywords)
    edited = copy.deepcopy(kws)
    edited["families"]["access"]["terms"].append("Zugangscode")
    edited["families"]["access"]["variants"]["Passwort"].append("Passwoort")
    edited["families"].pop("trade")
    cfg2 = config_from_dicts(edited, rules, th)
    assert find_hits(t, cfg2.keywords) != [] and cfg2.rules_version != load_config().rules_version
    assert llm.extraction_cache_key(segs, "swiss-ai/Apertus-v1.5-8B", "rev1", "prompt-v1", provider="apertus_aws") == key
    assert before == find_hits(t, load_config().keywords)
    # the key depends on content, model, revision and prompt only
    assert llm.extraction_cache_key(segs, "m", "rev1", "prompt-v1", provider="apertus_aws") != key
    assert llm.extraction_cache_key(segs, "swiss-ai/Apertus-v1.5-8B", "rev1", "prompt-v1", provider="openrouter") != key
    assert llm.extraction_cache_key(segs, "swiss-ai/Apertus-v1.5-8B", "rev1", "prompt-v2", provider="apertus_aws") != key
    assert "keyword" not in "".join(llm.extraction_cache_key.__code__.co_varnames)


@pytest.mark.parametrize("name", list(scenarios()))
def test_every_trace_validates_and_matches_paths(name):
    t = run(scenarios()[name])
    assert DecisionTrace.from_dict(t.to_dict()).decision == t.decision
    assert 0.0 <= t.risk_score <= 1.0 and 0.0 <= t.confidence <= 1.0
    assert t.versions.rules and t.why_not_flagged is None


# --------------------------------------------------------------------------- rules and gate details


def test_counter_evidence_lowers_risk():
    asked = fact("F1", "customer", "request", "credentials", ["s002"])
    alone = run([asked]).risk_score
    refused = run([asked, fact("F2", "advisor", "refuse", "credentials", ["s003"])])
    assert refused.risk_score < alone
    assert refused.decision == "no_alert"
    own = fact("F1", "customer", "request", "credentials", ["s002"], counter_evidence="joked")
    assert run([own]).risk_score < alone


def test_earlier_warning_does_not_excuse_a_later_disclosure():
    t = run([fact("F1", "advisor", "warn", "credentials", ["s003"]), fact("F2", "customer", "disclose", "credentials", ["s004"])])
    assert t.decision == "alarm"


def test_hypothetical_and_quote_acts_never_raise_risk():
    for act in ("hypothetical", "quote", "refuse", "warn"):
        assert run([fact("F1", "customer", act, "credentials", ["s004"])]).decision == "no_alert"


def test_dropped_fact_that_could_matter_is_missing_evidence():
    t = run([fact("F1", "customer", "disclose", "credentials", ["s004"], valid=False, drop_reason="quote mismatch")])
    assert (t.decision, t.decision_path) == ("review", "missing_evidence")


def test_dropped_fact_that_cannot_change_the_outcome_only_lowers_confidence():
    base = run([DISCLOSE_3P()])
    t = run([DISCLOSE_3P(), fact("F9", "customer", "disclose", "client_data", ["s004"], valid=False, drop_reason="x")])
    assert t.decision == "alarm"
    assert t.confidence_breakdown.components["missing_evidence"] < base.confidence_breakdown.components["missing_evidence"]


def test_fact_citing_unknown_segment_is_treated_as_dropped():
    t = run([fact("F1", "customer", "disclose", "credentials", ["s999"])])
    assert t.decision != "alarm" and not t.facts[0].valid and "s999" in t.facts[0].drop_reason


def test_needs_keyword_rules_do_not_fire_on_generic_requests():
    t = run([fact("F1", "customer", "request", "other", ["s006"])])
    assert not any(r.fired for r in t.rules)
    texts = {**TEXTS, "s006": ("customer", "Chönd mer die Zahlig ufteile, de Kontrolle umgah?")}
    t = run([fact("F1", "customer", "request", "other", ["s006"])], t=transcript(texts=texts))
    assert any(r.criterion == "control_evasion" and r.fired for r in t.rules)


def test_payment_card_data_alone_is_never_an_alarm():
    texts = {**TEXTS, "s006": ("customer", "Mini Kreditkartennummer isch 4111 1111.")}
    t = run([], t=transcript(texts=texts), config=with_thresholds(CFG, alarm=0.45, review=0.2))
    (r,) = [r for r in t.rules if r.criterion == "payment_card_data"]
    assert r.risk == 0.3 and not r.fired and t.decision != "alarm"


def benign_noisy():
    texts = {"s001": ("advisor", "Grüezi."), "s002": ("customer", "Wie spät isch es?"), "s003": ("advisor", "Halbi drü.")}
    return transcript(lp=-1.45, nsp=0.6, texts=texts), noisy_analysis(0.0)


# Worst-case audio alone scores ~0.51 with the placeholder weights (the structural components stay 1.0), so these
# tests raise the gate to 0.6 to put a noisy call below it.
GATE = lambda c: with_thresholds(c, confidence_gate=0.6)


def test_gate_scope_risky_only_keeps_harmless_noisy_call_no_alert():
    t, an = benign_noisy()
    out = run([], t=t, an=an, config=GATE(CFG))
    assert out.confidence < out.thresholds.confidence_gate
    assert (out.decision, out.decision_path) == ("no_alert", "no_alert")


def test_gate_scope_any_sends_harmless_noisy_call_to_review():
    t, an = benign_noisy()
    kws, rules, th = raw()
    th["confidence"]["gate_scope"] = "any"
    out = run([], t=t, an=an, config=GATE(config_from_dicts(kws, rules, th)))
    assert (out.decision, out.decision_path) == ("review", "low_confidence")


def test_gate_scope_risky_only_still_gates_when_keywords_present():
    t = transcript(lp=-1.45, nsp=0.6)
    out = run([], t=t, an=noisy_analysis(0.0), config=GATE(CFG))   # keyword hits present, no facts, low confidence
    assert (out.decision, out.decision_path) == ("review", "low_confidence")


def test_one_rule_per_criterion_and_other_disabled():
    t = run([])
    from pipeline.schemas import CRITERIA
    assert {r.criterion for r in t.rules} == set(CRITERIA) - {"other"}


def test_decide_reuses_inputs_without_mutation():
    facts = [DISCLOSE_3P()]
    before = copy.deepcopy(facts)
    run(facts)
    assert facts == before


# --------------------------------------------------------------------------- config validation


def test_bad_rules_rejected():
    _, rules, _ = raw()
    bad = copy.deepcopy(rules)
    bad["rules"] = [r for r in bad["rules"] if r["criterion"] != "control_evasion"]
    bad["rules"][0]["facts"][0]["when"]["act"] = "shout"
    bad["rules"][1]["facts"][0]["risk"] = 4
    with pytest.raises(ConfigError) as e:
        parse_rules(bad)
    msgs = " | ".join(e.value.errors)
    assert "missing a rule for criterion control_evasion" in msgs and "shout" in msgs and "risk" in msgs


def test_bad_thresholds_rejected():
    kws, rules, th = raw()
    th["review"] = 0.9
    with pytest.raises(ConfigError, match="review < alarm"):
        config_from_dicts(kws, rules, th)


# --------------------------------------------------------------------------- MOCK fixtures smoke test

FIX = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize("n, expected", [("001", "alarm"), ("002", "no_alert")])
def test_mock_fixture_facts_reproduce_the_mock_decision(n, expected):
    """MOCK data (invented): only shows the core agrees with the hand-written fixture traces."""
    tr = Transcript.from_dict(json.loads((FIX / f"call_MOCK_{n}.transcript.json").read_text()))
    an = AnalysisArtifact.from_dict(json.loads((FIX / f"call_MOCK_{n}.analysis.json").read_text()))
    facts = [Fact(**f) for f in json.loads((FIX / f"call_MOCK_{n}.trace.json").read_text())["facts"]]
    assert decide_call(tr, facts, an, CFG).decision == expected


def test_rules_version_changes_with_any_threshold_or_confidence_edit():
    kws, rules, th = raw()
    base = config_from_dicts(kws, rules, th).rules_version
    for edit in (lambda t: t["confidence"].update(formula="weighted_geometric"),
                 lambda t: t["confidence"].update(gate_scope="any"),
                 lambda t: t["confidence"]["weights"].update(asr=0.9),
                 lambda t: t["confidence"]["params"].update(proximity_margin=0.3),
                 lambda t: t.update(alarm=0.8)):
        th2 = copy.deepcopy(th)
        edit(th2)
        assert config_from_dicts(kws, rules, th2).rules_version != base
    assert config_from_dicts(kws, rules, copy.deepcopy(th)).rules_version == base
