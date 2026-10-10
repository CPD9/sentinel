"""What-if simulator: patches, flips with reasons, workload, feedback check, and the monotonicity / safety properties.

Synthetic corpus only (fixtures/whatif_corpus.py): no data/ and no artifacts/ needed.
"""
import copy
import json
import sys
import time
from pathlib import Path

import pytest

from pipeline.decide import config_from_dicts, decide_call
from pipeline.feedback import make_entry
from pipeline.keywords import ConfigError
from pipeline.schemas import DECISION_RANK, SimulationResult, StageError
from pipeline.simulate import (CallInputs, RawConfig, Simulator, apply_patch, credit, load_raw, merge_patches, patch_components,
                               patched_docs, simulate, split_patch, workload)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from whatif_corpus import SCENARIOS, make_call, make_corpus  # noqa: E402

RAW = load_raw()
CORPUS = make_corpus(40, seed=3, mock=False)


def rank(d):
    return DECISION_RANK[d]


# --------------------------------------------------------------------------- patches

def test_empty_patch_changes_nothing():
    r = simulate(CORPUS, {}, RAW)
    assert r.flipped == [] and r.counts["before"] == r.counts["after"]
    assert r.workload.delta_flagged_per_100 == 0 and r.baseline_version == r.patched_version
    assert r.feedback_check is None and r.n_calls == len(CORPUS)


def test_patched_docs_does_not_mutate_the_input_and_roundtrips_through_the_validator():
    before = copy.deepcopy((RAW.keywords, RAW.rules, RAW.thresholds))
    out = patched_docs(RAW, {"thresholds": {"alarm": 0.9}, "keywords": {"disable_families": ["trade"]}, "rules": {"disable": ["control_evasion"]}})
    assert (RAW.keywords, RAW.rules, RAW.thresholds) == before
    assert out.thresholds["alarm"] == 0.9 and "trade" not in out.keywords["families"]
    assert next(r for r in out.rules["rules"] if r["criterion"] == "control_evasion")["enabled"] is False
    assert apply_patch(RAW, {"thresholds": {"alarm": 0.9}}).thresholds.alarm == 0.9


@pytest.mark.parametrize("patch", [
    {"thresholds": {"alarm": 0.3}},                          # review (0.4) >= alarm
    {"thresholds": {"review": 0.8}},
    {"thresholds": {"alarm": 1.5}},
    {"thresholds": {"gate": 0.5}},                           # unknown key
    {"keywords": {"disable_families": ["nope"]}},
    {"rules": {"disable": ["nope"]}},
    {"colour": "red"},
])
def test_invalid_patch_is_a_config_error(patch):
    with pytest.raises(ConfigError):
        simulate(CORPUS, patch, RAW)


def test_patch_components_and_split_are_consistent():
    p = {"thresholds": {"alarm": 0.9, "review": 0.5}, "keywords": {"disable_families": ["trade", "access"]}, "rules": {"disable": ["insider_trading"]}}
    comps = patch_components(p)
    assert comps == ["thresholds.alarm=0.9", "thresholds.review=0.5", "keywords.disable:trade", "keywords.disable:access", "rules.disable:insider_trading"]
    parts = split_patch(p)
    assert [patch_components(x)[0] for x in parts] == comps
    merged = {}
    for x in parts:
        merged = merge_patches(merged, x)
    assert patch_components(merged) == patch_components({**p, "keywords": {"disable_families": ["access", "trade"]}})


# --------------------------------------------------------------------------- agreement with decide_call

@pytest.mark.parametrize("patch", [
    {"thresholds": {"alarm": 0.95}},
    {"thresholds": {"review": 0.6, "confidence_gate": 0.8}},
    {"keywords": {"disable_families": ["access", "trade"]}},
    {"rules": {"disable": ["credential_sharing"]}},
    {"thresholds": {"alarm": 0.85}, "rules": {"disable": ["third_party_disclosure"]}, "keywords": {"disable_families": ["numbers"]}},
])
def test_simulation_equals_a_direct_decide_call_run(patch):
    r = simulate(CORPUS, patch, RAW)
    cfg = patched_docs(RAW, patch).build()
    flips = {}
    for c in CORPUS:
        b = decide_call(c.transcript, c.facts, None, RAW.build()).decision      # no hits cache, no shortcut
        a = decide_call(c.transcript, c.facts, None, cfg).decision
        if a != b:
            flips[c.call_id] = (b, a)
    assert {f.call_id: (f.before, f.after) for f in r.flipped} == flips
    assert r.counts["after"] == {d: sum(1 for c in CORPUS if decide_call(c.transcript, c.facts, None, cfg).decision == d) for d in r.counts["after"]}


def test_result_validates_serialises_and_explains_each_flip():
    r = simulate(CORPUS, {"thresholds": {"alarm": 0.9}}, RAW)
    assert r.flipped, "corpus should have alarms between 0.7 and 0.9"
    assert SimulationResult.validate(r.to_dict()) == []
    assert SimulationResult.from_dict(json.loads(json.dumps(r.to_dict()))).to_dict() == r.to_dict()
    for f in r.flipped:
        assert f.direction == "down" and f.reasons[0].startswith("decision path") and f.attributed_to == ["thresholds.alarm=0.9"]
    assert [f.direction for f in r.flipped] == sorted((f.direction for f in r.flipped), key=lambda d: d != "up")


def test_attribution_names_the_knob_that_causes_each_flip():
    # password_asked has risk 0.85 -> only the alarm threshold moves it; insider_request goes with its rule.
    calls = [make_call("call_a", "password_asked"), make_call("call_b", "insider_request"), make_call("call_c", "greeting")]
    sim = Simulator(calls, RAW)
    both = {"thresholds": {"alarm": 0.95}, "rules": {"disable": ["insider_trading"]}}
    by_call = {f.call_id: f for f in sim.run(both).flipped}
    assert by_call["call_a"].attributed_to == ["thresholds.alarm=0.95"]
    assert by_call["call_b"].attributed_to and all(a in patch_components(both) for a in by_call["call_b"].attributed_to)
    for f in by_call.values():                                  # every attributed knob alone reproduces the flip
        for comp in f.attributed_to:
            solo = next(p for p in split_patch(both) if patch_components(p) == [comp])
            assert sim.decisions(solo)[f.call_id] == f.after
    assert "call_c" not in by_call


def test_disabling_a_rule_or_family_reports_the_reason():
    calls = [make_call("call_a", "password_asked")]
    r = Simulator(calls, RAW).run({"rules": {"disable": ["credential_sharing"]}})
    (f,) = r.flipped
    assert f.after in ("no_alert", "review") and any("credential_sharing" in x for x in f.reasons)
    r2 = Simulator(calls, RAW).run({"keywords": {"disable_families": ["access"]}})
    assert any("keyword hits" in x for x in r2.flipped[0].reasons) if r2.flipped else True


# --------------------------------------------------------------------------- workload

def test_workload_counts_alarms_and_reviews_per_100():
    w = workload(["alarm"] * 3 + ["review"] * 5 + ["no_alert"] * 12)
    assert (w.n, w.alarms_per_100, w.reviews_per_100, w.flagged_per_100) == (20, 15.0, 25.0, 40.0)
    assert workload([]).flagged_per_100 == 0.0


def test_workload_delta_matches_counts():
    r = simulate(CORPUS, {"thresholds": {"review": 0.6}}, RAW)
    n = r.n_calls
    flagged = lambda c: c["alarm"] + c["review"]
    assert r.workload.before.flagged_per_100 == round(100 * flagged(r.counts["before"]) / n, 2)
    assert r.workload.after.flagged_per_100 == round(100 * flagged(r.counts["after"]) / n, 2)
    assert r.workload.delta_flagged_per_100 == round(r.workload.after.flagged_per_100 - r.workload.before.flagged_per_100, 2)


# --------------------------------------------------------------------------- monotonicity and safety

@pytest.mark.parametrize("seed", range(6))
def test_raising_alarm_never_makes_a_call_more_severe(seed):
    calls = make_corpus(30, seed=seed, mock=False)
    sim = Simulator(calls, RAW)
    prev = None
    for a in [0.41, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]:
        d = sim.decisions({"thresholds": {"alarm": a}})
        if prev:
            assert all(rank(d[c]) <= rank(prev[c]) for c in d), (seed, a, [c for c in d if rank(d[c]) > rank(prev[c])])
        prev = d


@pytest.mark.parametrize("seed", range(6))
def test_raising_review_never_makes_a_call_more_severe(seed):
    calls = make_corpus(30, seed=seed, mock=False)
    sim = Simulator(calls, RAW)
    prev = None
    for r_ in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.69]:
        d = sim.decisions({"thresholds": {"review": r_}})
        if prev:
            assert all(rank(d[c]) <= rank(prev[c]) for c in d), (seed, r_)
        prev = d


@pytest.mark.parametrize("seed", range(6))
def test_raising_the_gate_never_creates_an_alarm(seed):
    calls = make_corpus(30, seed=seed, mock=False)
    sim = Simulator(calls, RAW)
    prev = None
    for g in [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 0.95, 1.0]:
        d = sim.decisions({"thresholds": {"confidence_gate": g}})
        if prev:
            assert all(not (d[c] == "alarm" and prev[c] != "alarm") for c in d), (seed, g)
        prev = d


def test_alarm_count_is_monotone_in_each_threshold():
    sim = Simulator(CORPUS, RAW)
    n_alarm = lambda p: list(sim.decisions(p).values()).count("alarm")
    by_alarm = [n_alarm({"thresholds": {"alarm": a}}) for a in (0.45, 0.6, 0.75, 0.9, 1.0)]
    assert by_alarm == sorted(by_alarm, reverse=True)
    by_gate = [n_alarm({"thresholds": {"confidence_gate": g}}) for g in (0.0, 0.3, 0.6, 0.9, 1.0)]
    assert by_gate == sorted(by_gate, reverse=True)


def test_stage_errored_calls_never_flip_under_any_patch():
    broken = make_call("call_err", "password_asked")
    broken.stage_errors = [StageError("asr", "boom")]
    no_facts = CallInputs(make_call("call_nof", "password_asked").transcript, None)
    sim = Simulator([broken, no_facts, make_call("call_ok", "password_asked")], RAW)
    assert sim.run({}).n_locked == 2
    for patch in [{"thresholds": {"alarm": 0.99}}, {"thresholds": {"review": 0.0, "alarm": 0.01}}, {"rules": {"disable": ["credential_sharing"]}},
                  {"thresholds": {"confidence_gate": 0.0}}, {"thresholds": {"confidence_gate": 1.0}}]:
        d = sim.decisions(patch)
        assert d["call_err"] == "review" == d["call_nof"], patch


def test_no_valid_supporting_fact_is_never_an_alarm_whatever_the_thresholds():
    calls = [make_call("call_none", "card_number"), make_call("call_mention", "greeting"), make_call("call_g", "password_warning")]
    sim = Simulator(calls, RAW)
    for a in (0.01, 0.1, 0.3, 0.5):
        for r_ in (0.0, 0.005):
            for g in (0.0, 0.5, 1.0):
                d = sim.decisions({"thresholds": {"alarm": a, "review": min(r_, a - 0.001), "confidence_gate": g}})
                assert "alarm" not in d.values(), (a, r_, g, d)


def test_dropped_facts_never_alarm_under_any_alarm_threshold():
    c = make_call("call_dropped", "password_asked")
    c.facts = [type(f)(**{**f.__dict__, "valid": False, "drop_reason": "quote mismatch"}) for f in c.facts]
    sim = Simulator([c], RAW)
    assert all(sim.decisions({"thresholds": {"alarm": a, "review": a / 2}})["call_dropped"] != "alarm" for a in (0.01, 0.2, 0.5, 0.7))


# --------------------------------------------------------------------------- feedback check

@pytest.mark.parametrize("verdict,before,after,expected", [
    ("correct", "alarm", "alarm", (0.0, False)), ("correct", "alarm", "review", (0.0, True)), ("correct", "no_alert", "review", (0.0, True)),
    ("false_alarm", "alarm", "review", (0.5, False)), ("false_alarm", "alarm", "no_alert", (1.0, False)), ("false_alarm", "review", "no_alert", (1.0, False)),
    ("false_alarm", "review", "review", (0.0, False)), ("false_alarm", "review", "alarm", (0.0, True)), ("false_alarm", "no_alert", "review", (0.0, True)),
    ("false_alarm", "no_alert", "no_alert", (0.0, False)),
    ("missed", "no_alert", "review", (0.5, False)), ("missed", "no_alert", "alarm", (1.0, False)), ("missed", "review", "alarm", (1.0, False)),
    ("missed", "review", "no_alert", (0.0, True)), ("missed", "alarm", "alarm", (0.0, False)), ("missed", "alarm", "review", (0.0, True)),
])
def test_credit_table(verdict, before, after, expected):
    assert credit(verdict, before, after) == expected


def test_feedback_check_lists_fixed_unchanged_and_violations():
    calls = [make_call("call_a", "password_asked"), make_call("call_b", "password_asked"), make_call("call_c", "greeting"), make_call("call_d", "password_warning")]
    base = Simulator(calls, RAW)
    assert base.baseline["call_a"].decision == "alarm" and base.baseline["call_c"].decision == "no_alert"
    fb = {"call_a": make_entry("call_a", "false_alarm", "alarm"), "call_b": make_entry("call_b", "correct", "alarm"),
          "call_c": make_entry("call_c", "missed", "no_alert"), "call_d": make_entry("call_d", "correct", "no_alert"), "call_zzz": make_entry("call_zzz", "correct", "alarm")}
    sim = Simulator(calls, RAW, fb)
    assert set(sim.feedback) == {"call_a", "call_b", "call_c", "call_d"}      # verdicts for unknown calls are ignored
    r = sim.run({"thresholds": {"alarm": 0.95}})                              # a and b are identical: both go to review
    fc = r.feedback_check
    assert fc.violations == ["call_b"] and fc.fixed == ["call_a"] and sorted(fc.unchanged) == ["call_c", "call_d"]
    assert fc.fix_credit == 0.5 and fc.n_feedback == 4
    assert {f.call_id: f.feedback_verdict for f in r.flipped} == {"call_a": "false_alarm", "call_b": "correct"}


def test_simulation_is_fast():
    calls = make_corpus(60, seed=1, mock=False)
    t = time.perf_counter()
    simulate(calls, {"thresholds": {"alarm": 0.9}, "rules": {"disable": ["insider_trading"]}}, RAW)
    assert time.perf_counter() - t < 1.0                                       # API.md promise: < 1 s for 60 calls


def test_all_scenarios_decide_without_error():
    for name in SCENARIOS:
        assert Simulator([make_call("call_x", name)], RAW).baseline["call_x"].decision in ("alarm", "review", "no_alert")
