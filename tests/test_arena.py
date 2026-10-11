"""scripts/arena.py: case-manifest-only call ids, the remote gate stops the run, leaderboard math. No network."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import arena  # noqa: E402

from pipeline import llm  # noqa: E402
from pipeline.llm import ProviderNotPermitted  # noqa: E402


def test_check_calls_refuses_non_manifest_ids():
    allowed = ["call_001", "call_002"]
    assert arena.check_calls(None, allowed) == allowed
    assert arena.check_calls(["call_002"], allowed) == ["call_002"]
    for bad in (["call_999"], ["upload_1"], ["../data/x.wav"], ["call_001", "call_x001"]):
        with pytest.raises(arena.CallRefused):
            arena.check_calls(bad, allowed)


def test_main_exits_2_on_non_manifest_call(monkeypatch, capsys):
    monkeypatch.setattr(arena, "manifest_ids", lambda: ["call_001"])
    assert arena.main(["--calls", "call_999", "--no-remote"]) == 2
    assert "refused" in capsys.readouterr().err


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", boom)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")


def test_remote_lane_refused_without_opt_in(monkeypatch, no_network):
    monkeypatch.delenv(llm.ALLOW_REMOTE_ENV, raising=False)
    with pytest.raises(ProviderNotPermitted):
        arena.run_remote("qwen/qwen-2.5-72b-instruct", ["call_001"], 1)


def test_remote_lane_refuses_off_allowlist_model(monkeypatch, no_network):
    monkeypatch.setenv(llm.ALLOW_REMOTE_ENV, llm.ALLOW_REMOTE_VALUE)
    with pytest.raises(ProviderNotPermitted):
        arena.run_remote("openai/gpt-4o", ["call_001"], 1)


def test_score_run(monkeypatch):
    gold = {"a": True, "b": True, "c": False, "d": False}
    monkeypatch.setattr(arena.evaluate, "escalation_auc",
                        lambda s: {"auc": 0.75, "ci95": [0.5, 1.0], "n": len(s), "n_positive": 2, "by_split": {}})

    def score(dec):
        tp = sum(1 for c, d in dec.items() if gold[c] and d != "no_alert")
        fp = sum(1 for c, d in dec.items() if not gold[c] and d != "no_alert")
        return {"all": {"escalation": {"tp": tp, "fp": fp, "fn": 2 - tp, "tn": 2 - fp, "precision": None,
                                       "recall": None}}}
    monkeypatch.setattr(arena.evaluate, "score_decisions", score)
    cite = lambda ok: {"valid": ok, "segment_ids": ["S0001"]}
    m = lambda ms, cost: [{"wall_ms": ms, "cost_usd": cost}]
    run = {"slug": "x", "model": "x", "provider": "openrouter", "self_hosted": False, "calls": {
        "a": {"decision": "alarm", "risk": 0.9, "citations": [cite(True)], "metrics": m(100, 0.01), "error": None},
        "b": {"error": "boom"},
        "c": {"decision": "review", "risk": 0.6, "citations": [cite(False)], "metrics": m(300, 0.02), "error": None},
        "d": {"decision": "no_alert", "risk": 0.1, "citations": [], "metrics": m(200, 0.01), "error": None}}}
    r = arena.score_run(run, ["a", "b", "c", "d"])
    assert (r["errors"], r["error_calls"]) == (1, ["b"])          # an error counts as a miss, never hidden
    assert (r["false_alarms"], r["missed"]) == (1, 1)
    assert r["balanced_accuracy"] == 0.5
    assert (r["citations_valid"], r["citations_total"], r["flagged_without_valid_citation"]) == (1, 2, 1)
    assert r["latency_ms_median"] == 200 and r["cost_usd"] == 0.04
