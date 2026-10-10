"""Milestone 2.5: MOCK fixtures validate, agree with each other, match docs/PRODUCT.md, and are reproducible."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from pipeline.schemas import (
    AnalysisArtifact, CallListItem, CallResult, DecisionTrace, FeedbackEntry, ProcessingEvent, QualityReport, SimulationResult,
    SuggestionsResponse, Transcript, validate_call_result,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
SCHEMA_BY_SUFFIX = {".transcript.json": Transcript, ".trace.json": DecisionTrace,
                    ".analysis.json": AnalysisArtifact}
SNIPPET_PAD_S = 10.0


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def fixture_files() -> list[Path]:
    return sorted(p for p in FIX.glob("*.json"))


def test_fixture_set_is_complete():
    names = {p.name for p in fixture_files()}
    assert {"calls.json", "quality_report.json", "call_MOCK_001.result.json", "call_MOCK_001.transcript.json",
            "call_MOCK_001.trace.json", "call_MOCK_001.analysis.json", "call_MOCK_001.events.json",
            "call_MOCK_002.result.json", "call_MOCK_002.trace.json", "call_MOCK_004.result.json",
            "feedback.json", "simulation.json", "suggestions.json", "whatif_calls.json"} <= names


@pytest.mark.parametrize("path", fixture_files(), ids=lambda p: p.name)
def test_fixture_validates_and_is_marked_mock(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    name = path.name
    if name == "calls.json":
        for row in d:
            assert CallListItem.validate(row) == []
            assert row["is_mock"] is True
    elif name.endswith(".events.json"):
        for e in d:
            assert ProcessingEvent.validate(e) == []
    elif name == "feedback.json":
        for e in d:
            assert FeedbackEntry.validate(e) == [] and e["is_mock"] is True
    elif name == "simulation.json":
        assert SimulationResult.validate(d) == [] and d["is_mock"] is True
    elif name == "suggestions.json":
        assert SuggestionsResponse.validate(d) == [] and d["is_mock"] is True
    elif name == "whatif_calls.json":
        assert d["is_mock"] is True and all(c["call_id"].startswith("call_MOCK_1") for c in d["calls"])
    elif name == "quality_report.json":
        assert QualityReport.validate(d) == []
        assert d["is_mock"] is True and d["provider"] == "MOCK"
    elif name.endswith(".result.json"):
        assert validate_call_result(d) == []
        CallResult.from_dict(d)
        assert d["narrative"].startswith("[MOCK]")
        assert {v for v in d["versions"].values() if v is not None} == {"MOCK"}
    else:
        schema = next(s for suf, s in SCHEMA_BY_SUFFIX.items() if name.endswith(suf))
        assert schema.validate(d) == []
        assert schema.from_dict(d).to_dict() == d          # lossless roundtrip
        assert d["is_mock"] is True


@pytest.mark.parametrize("cid", ["call_MOCK_001", "call_MOCK_002"])
def test_call_documents_agree(cid):
    res, tr = load(f"{cid}.result.json"), load(f"{cid}.transcript.json")
    trace, an = load(f"{cid}.trace.json"), load(f"{cid}.analysis.json")
    segs = {s["id"]: s for s in tr["segments"]}
    dur = an["duration_s"]
    assert tr["duration_s"] == dur

    for f in res["findings"]:
        for e in f["evidence"] + f["counter_evidence"]:
            cited = [segs[i] for i in e["segment_ids"]]                   # KeyError = dangling ref
            assert {c["speaker"] for c in cited} == {e["speaker"]}
            assert e["start_s"] == min(c["start_s"] for c in cited)
            assert e["end_s"] == max(c["end_s"] for c in cited)
            assert e["text"] in " ".join(c["text"] for c in cited)        # verbatim quote
            lo, hi = max(0.0, e["start_s"] - SNIPPET_PAD_S), min(dur, e["end_s"] + SNIPPET_PAD_S)
            assert 0 <= lo < hi <= dur                                     # snippet window clamps cleanly

    windows = [(w["finding_index"], w["evidence_index"], w["start_s"], w["end_s"], w["criterion"])
               for w in an["evidence_windows"]]
    expected = [(fi, ei, e["start_s"], e["end_s"], f["criterion"])
                for fi, f in enumerate(res["findings"]) for ei, e in enumerate(f["evidence"])]
    assert windows == expected

    assert (trace["decision"], trace["risk_score"], trace["confidence"]) == \
        (res["decision"], res["risk_score"], res["confidence"])
    assert trace["confidence_breakdown"]["components"]["audio_quality"] == an["audio_quality"]["call_score"]
    for fact in trace["facts"]:
        assert all(i in segs for i in fact["segment_ids"])
        if fact["valid"]:
            cited = " ".join(segs[i]["text"] for i in fact["segment_ids"])
            assert fact["quote"] in cited and {segs[i]["speaker"] for i in fact["segment_ids"]} == {fact["speaker"]}
    assert all(h["segment_id"] in segs and h["matched_text"] in segs[h["segment_id"]]["text"]
               for h in trace["keyword_hits"])
    asr = {p["segment_id"]: p for p in an["asr_confidence"]["segments"]}
    assert all(asr[i]["avg_logprob"] == s["avg_logprob"] for i, s in segs.items())
    assert an["feature_maps"] is None and an["feature_maps_status"] == "not_computed"


def test_harmless_keyword_call_is_no_alert_with_explanation():
    res, trace = load("call_MOCK_002.result.json"), load("call_MOCK_002.trace.json")
    assert res["decision"] == "no_alert" and trace["keyword_hits"]
    assert not any(r["fired"] for r in trace["rules"]) and trace["why_not_flagged"]


def test_whatif_fixtures_agree_with_each_other():
    calls, sugg, sim, fb = load("whatif_calls.json"), load("suggestions.json"), load("simulation.json"), load("feedback.json")
    ids = {c["call_id"] for c in calls["calls"]}
    counts = {d: sum(c["decision"] == d for c in calls["calls"]) for d in ("alarm", "review", "no_alert")}
    assert sim["counts"]["before"] == counts and sim["n_calls"] == len(ids) and sugg["config_version"] == calls["config_version"]
    assert {e["call_id"] for e in fb} <= ids and sugg["n_feedback"] == len(fb)
    assert sugg["suggestions"] and sugg["suggestions"][0]["fix_credit"] >= sugg["suggestions"][-1]["fix_credit"]
    for s in sugg["suggestions"]:
        assert s["effect"]["counts"]["before"] == counts and s["effect"]["feedback_check"]["violations"] == []
        assert {f["call_id"] for f in s["effect"]["flipped"]} <= ids
        assert s["effect"]["baseline_version"] == s["config_version"]
    correct = {e["call_id"] for e in fb if e["verdict"] == "correct"}
    assert all(not correct & {f["call_id"] for f in s["effect"]["flipped"]} for s in sugg["suggestions"])


def test_inbox_rows_match_results():
    rows = {r["call_id"]: r for r in load("calls.json")}
    for cid in ("call_MOCK_001", "call_MOCK_002", "call_MOCK_004"):
        res = load(f"{cid}.result.json")
        row = rows[cid]
        assert (row["decision"], row["risk_score"], row["confidence"], row["n_stage_errors"]) == \
            (res["decision"], res["risk_score"], res["confidence"], len(res["stage_errors"]))
        assert row["status"] == ("error" if res["stage_errors"] else "done")
    assert rows["call_MOCK_003"]["status"] == "processing" and rows["call_MOCK_003"]["decision"] is None


def test_events_tell_a_complete_story():
    evs = load("call_MOCK_001.events.json")
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
    assert evs[0]["event"] == "job_queued" and evs[-1]["event"] == "job_finished"
    assert evs[-1]["decision"] == load("call_MOCK_001.result.json")["decision"]
    started = [e["stage"] for e in evs if e["event"] == "stage_started"]
    finished = [e["stage"] for e in evs if e["event"] == "stage_finished"]
    assert started == finished
    assert [e["ts"] for e in evs] == sorted(e["ts"] for e in evs)


def test_quality_report_is_internally_consistent():
    q = load("quality_report.json")
    n = q["overall"]["n"]
    assert sum(b["n"] for b in q["reliability"]["bins"]) == n
    assert {(a["name"], a["transcript"]) for a in q["ablations"]} == \
        {(x, t) for x in ("keyword_only", "llm_only", "combined") for t in ("reference", "asr")}
    combined_asr = next(a for a in q["ablations"] if (a["name"], a["transcript"]) == ("combined", "asr"))
    assert combined_asr["conventions"] == q["overall"]


def test_regeneration_is_byte_identical(tmp_path):
    spec = importlib.util.spec_from_file_location("make_fixtures", FIX / "make_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--out", str(tmp_path)]) == 0
    generated = sorted(p.name for p in tmp_path.glob("*.json"))
    assert generated == [p.name for p in fixture_files()]
    for name in generated:
        assert (tmp_path / name).read_bytes() == (FIX / name).read_bytes(), f"{name} drifted: rerun make_fixtures.py"


# --------------------------------------------------------------------------- docs/PRODUCT.md paths

PATH_RE = re.compile(r"`((?:result|transcript|trace|analysis|quality|event|simulation|suggestions|feedback\[\]|calls\[\])(?:\.(?!json`)[A-Za-z_]\w*(?:\[\])?)+)`")
DOC_GLOBS = {"result": "*.result.json", "transcript": "*.transcript.json", "trace": "*.trace.json",
             "analysis": "*.analysis.json", "quality": "quality_report.json", "event": "*.events.json",
             "calls[]": "calls.json", "simulation": "simulation.json", "suggestions": "suggestions.json", "feedback[]": "feedback.json"}


def _resolves(doc, tokens: list[str]) -> bool:
    if not tokens:
        return True
    tok, rest = tokens[0], tokens[1:]
    key, is_list = tok.removesuffix("[]"), tok.endswith("[]")
    if not isinstance(doc, dict) or key not in doc:
        return False
    v = doc[key]
    if is_list:
        return isinstance(v, list) and any(_resolves(x, rest) for x in v)
    return _resolves(v, rest) if rest else True


def _product_paths() -> tuple[list[str], str]:
    text = (ROOT / "docs" / "PRODUCT.md").read_text(encoding="utf-8")
    stretch = re.search(r"<!-- stretch:start -->.*?<!-- stretch:end -->", text, re.S)
    assert stretch, "PRODUCT.md must keep the STRETCH section markers"
    core = text[:stretch.start()] + text[stretch.end():]
    return sorted(set(PATH_RE.findall(core))), stretch.group(0)


def test_product_doc_paths_exist_in_fixtures():
    """Each path must exist in at least one fixture of its document type."""
    paths, _ = _product_paths()
    assert len(paths) > 80, "path extraction broke"
    missing = []
    for p in paths:
        prefix, _, rest = p.partition(".")
        docs = [load(f.name) for f in FIX.glob(DOC_GLOBS[prefix])]
        if not any(_resolves({"_": d} if isinstance(d, list) else d,
                             (["_[]"] if isinstance(d, list) else []) + rest.split(".")) for d in docs):
            missing.append(p)
    assert missing == []


def test_no_ui_element_depends_on_feature_maps():
    paths, stretch = _product_paths()
    assert not [p for p in paths if "feature_maps" in p or "audio_quality_cnn" in p]
    assert "analysis.feature_maps" in stretch
