"""Suggestion search: never flips a confirmed-correct call, ranks by smallest effective change, never applies anything,
and never touches ground-truth labels. Synthetic corpus only."""
import ast
import copy
import random
import sys
import time
from pathlib import Path

import pytest

from pipeline.decide import decide_call
from pipeline.feedback import make_entry
from pipeline.schemas import DECISION_RANK, SuggestionsResponse
from pipeline.simulate import Simulator, load_raw, patch_components, patched_docs
from pipeline.suggest import CAVEAT, suggest, suggestions_response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))
from whatif_corpus import make_call, make_corpus  # noqa: E402

RAW = load_raw()


def random_feedback(calls, seed, frac=0.5):
    """Officer-style verdicts, valid for each call's current decision."""
    rng = random.Random(seed)
    base = Simulator(calls, RAW).baseline
    fb = {}
    for c in calls:
        if rng.random() > frac:
            continue
        d = base[c.call_id].decision
        verdict = rng.choice([v for v in ("false_alarm", "missed", "correct", "correct") if not (v == "false_alarm" and d == "no_alert") and not (v == "missed" and d == "alarm")])
        fb[c.call_id] = make_entry(c.call_id, verdict, d)
    return fb


def independent_decisions(calls, patch):
    """Re-decide from scratch with plain decide_call: no Simulator, no hits cache."""
    cfg = patched_docs(RAW, patch).build()
    return {c.call_id: decide_call(c.transcript, c.facts, c.analysis, cfg, c.stage_errors or None).decision for c in calls}


# --------------------------------------------------------------------------- the safety property

@pytest.mark.parametrize("seed", range(8))
def test_no_suggestion_flips_a_correct_call_or_moves_a_labelled_call_the_wrong_way(seed):
    calls = make_corpus(24, seed=seed, mock=False)
    fb = random_feedback(calls, seed)
    base = {c: d for c, d in independent_decisions(calls, {}).items()}
    for s in suggest(calls, fb, RAW):
        after = independent_decisions(calls, s.patch)                  # checked outside the search machinery
        for cid, e in fb.items():
            b, a = DECISION_RANK[base[cid]], DECISION_RANK[after[cid]]
            if e.verdict == "correct":
                assert a == b, (seed, s.title, cid)
            elif e.verdict == "false_alarm":
                assert a <= b, (seed, s.title, cid)
            else:
                assert a >= b, (seed, s.title, cid)
        assert s.effect.feedback_check.violations == []
        assert s.fix_credit > 0 and s.fix_credit == s.effect.feedback_check.fix_credit
        assert s.config_version == s.effect.baseline_version


def test_only_fix_conflicts_with_a_correct_call_returns_nothing_with_a_reason():
    twins = [make_call("call_a", "password_asked"), make_call("call_b", "password_asked")]     # identical in every respect
    fb = {"call_a": make_entry("call_a", "false_alarm", "alarm"), "call_b": make_entry("call_b", "correct", "alarm")}
    assert suggest(twins, fb, RAW) == []
    resp = suggestions_response(twins, fb, RAW)
    assert resp.suggestions == [] and resp.reason.startswith("No single change or small combination")
    assert SuggestionsResponse.validate(resp.to_dict()) == []


def test_a_fix_exists_when_the_correct_call_is_different():
    calls = [make_call("call_a", "password_asked"), make_call("call_b", "insider_mention")]
    sim = Simulator(calls, RAW)
    assert sim.baseline["call_a"].decision == "alarm"
    fb = {"call_a": make_entry("call_a", "false_alarm", "alarm"), "call_b": make_entry("call_b", "correct", sim.baseline["call_b"].decision)}
    top = suggest(calls, fb, RAW)
    assert top and top[0].fixed == ["call_a"] and top[0].n_knobs == 1
    assert top[0].effect.feedback_check.violations == []


# --------------------------------------------------------------------------- ranking

def test_suggestions_are_ranked_and_free_of_dominated_or_duplicate_entries():
    for seed in range(8):
        calls = make_corpus(40, seed=seed, mock=False)
        sugg = suggest(calls, random_feedback(calls, seed, 0.6), RAW, max_results=8)
        keys = [(-round(s.fix_credit, 6), len(s.collateral_flips), s.n_knobs) for s in sugg]
        assert keys == sorted(keys), seed
        assert len({s.id for s in sugg}) == len(sugg)
        comps = [frozenset(patch_components(s.patch)) for s in sugg]
        for i, a in enumerate(sugg):
            for j, b in enumerate(sugg):
                if i != j and comps[i] < comps[j]:           # a strictly smaller change must not also be offered with no better result
                    assert not (a.fix_credit >= b.fix_credit and len(a.collateral_flips) <= len(b.collateral_flips)), (seed, a.title, b.title)
        decided = [tuple(sorted((f.call_id, f.after) for f in s.effect.flipped)) for s in sugg]
        assert len(set(decided)) == len(decided), "two suggestions with the same effect on every call"


def test_smaller_change_wins_over_a_bigger_one_with_the_same_effect():
    calls = [make_call("call_a", "password_asked"), make_call("call_b", "greeting")]
    fb = {"call_a": make_entry("call_a", "false_alarm", "alarm")}
    sugg = suggest(calls, fb, RAW, max_results=10)
    assert sugg[0].n_knobs == 1
    assert all(s.n_knobs == 1 or s.fix_credit > sugg[0].fix_credit or len(s.collateral_flips) < len(sugg[0].collateral_flips) for s in sugg)


def test_suggestions_are_deterministic():
    calls = make_corpus(30, seed=2, mock=False)
    fb = random_feedback(calls, 2)
    a = [s.to_dict() if hasattr(s, "to_dict") else s for s in suggest(calls, fb, RAW)]
    b = [s.to_dict() if hasattr(s, "to_dict") else s for s in suggest(calls, fb, RAW)]
    assert a == b


def test_every_suggestion_is_a_valid_patch_that_the_simulator_reproduces():
    calls = make_corpus(30, seed=5, mock=False)
    fb = random_feedback(calls, 5, 0.7)
    sim = Simulator(calls, RAW, fb)
    for s in suggest(calls, fb, RAW):
        again = sim.run(s.patch)
        assert again.to_dict() == s.effect.to_dict()
        assert set(s.fixed) | set(s.not_fixed) == {c for c, e in fb.items() if e.verdict != "correct"}
        assert not set(s.collateral_flips) & set(fb)


# --------------------------------------------------------------------------- empty results always say why

def test_empty_reasons():
    calls = [make_call("call_a", "password_asked"), make_call("call_b", "greeting")]
    assert suggestions_response(calls, {}, RAW).reason.startswith("No officer feedback yet")
    only_ok = {"call_a": make_entry("call_a", "correct", "alarm")}
    r = suggestions_response(calls, only_ok, RAW)
    assert r.suggestions == [] and r.reason.startswith("Only 'correct'") and r.counts_by_verdict == {"false_alarm": 0, "missed": 0, "correct": 1}
    stale = {"call_b": make_entry("call_b", "false_alarm", "review")}      # the officer saw review; today it is already no_alert
    r = suggestions_response(calls, stale, RAW)
    assert r.suggestions == [] and "already resolved" in r.reason
    for resp in (r, suggestions_response(calls, {}, RAW)):
        assert SuggestionsResponse.validate(resp.to_dict()) == []


def test_response_carries_counts_caveat_and_validates():
    calls = make_corpus(40, seed=1, mock=False)
    fb = random_feedback(calls, 1, 0.5)
    resp = suggestions_response(calls, fb, RAW)
    assert resp.n_feedback == len(fb) and sum(resp.counts_by_verdict.values()) == len(fb)
    assert resp.caveat == CAVEAT.format(n=len(fb)) and "not validated on unseen calls" in resp.caveat
    assert SuggestionsResponse.validate(resp.to_dict()) == []


def test_unknown_call_feedback_is_ignored():
    calls = [make_call("call_a", "password_asked")]
    resp = suggestions_response(calls, {"call_nope": make_entry("call_nope", "false_alarm", "alarm")}, RAW)
    assert resp.n_feedback == 0 and resp.suggestions == []


# --------------------------------------------------------------------------- never auto-apply, label isolation, speed

def test_suggesting_never_changes_the_config(tmp_path):
    raw = load_raw()
    before = copy.deepcopy((raw.keywords, raw.rules, raw.thresholds))
    calls = make_corpus(30, seed=4, mock=False)
    suggest(calls, random_feedback(calls, 4), raw)
    assert (raw.keywords, raw.rules, raw.thresholds) == before
    source = (ROOT / "pipeline" / "suggest.py").read_text() + (ROOT / "pipeline" / "simulate.py").read_text()
    assert "write_text" not in source and "open(" not in source.replace("def open(", "")


ISOLATED = ("simulate.py", "suggest.py", "feedback.py")
ALLOWED_PIPELINE = {"pipeline.schemas", "pipeline.decide", "pipeline.keywords", "pipeline.rules", "pipeline.confidence",
                    "pipeline.simulate", "pipeline.suggest", "pipeline.feedback"}


@pytest.mark.parametrize("name", ISOLATED)
def test_label_isolation_is_structural(name):
    path = ROOT / "pipeline" / name
    src = path.read_text(encoding="utf-8")
    for needle in ("evaluation.json", "manifests", "inference.json", "Stufe", "pipeline.evaluate", "pipeline import evaluate", "labels"):
        assert needle not in src, f"{name} mentions {needle!r}"
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pipeline"):
            mods |= {node.module} | {f"{node.module}.{a.name}" for a in node.names if f"{node.module}.{a.name}" in ALLOWED_PIPELINE | {"pipeline.evaluate", "pipeline.reference"}}
        elif isinstance(node, ast.Import):
            mods |= {a.name for a in node.names if a.name.startswith("pipeline")}
    assert {m for m in mods if m.startswith("pipeline.")} <= ALLOWED_PIPELINE, mods
    assert not any(m in mods for m in ("pipeline.evaluate", "pipeline.reference"))


def test_suggest_runs_without_the_evaluate_module_loaded():
    import subprocess
    code = ("import sys; sys.path.insert(0, 'fixtures'); from pipeline.suggest import suggest; from whatif_corpus import make_corpus; "
            "suggest(make_corpus(5, mock=False), {}); assert 'pipeline.evaluate' not in sys.modules and 'pipeline.reference' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_suggestion_search_stays_within_budget():
    calls = make_corpus(60, seed=1, mock=False)
    fb = random_feedback(calls, 1, 0.3)
    t = time.perf_counter()
    suggest(calls, fb, RAW)
    elapsed = time.perf_counter() - t
    assert elapsed < 5.0, elapsed           # design budget is 2 s for 60 calls; the margin keeps slow CI machines green
