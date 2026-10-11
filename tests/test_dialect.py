import copy
import json
import sys
from pathlib import Path

import pytest

from pipeline.schemas import DialectEstimate, SchemaError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dialect_map as dm  # noqa: E402

LANGID = {"call_id": "call_041", "model": "faster-whisper-large-v3-turbo@0a363e9161cb",
          "speakers": {"advisor": {"speech_s": 140.0, "chunks": 6, "probs": {"de": 0.97, "en": 0.01, "nl": 0.02}},
                       "customer": {"speech_s": 9.0, "chunks": 1, "probs": {"de": 0.5, "fr": 0.3, "it": 0.2}}}}
RESEARCH = {"cv_accuracy": 0.6, "cv_ci95": [0.4, 0.75], "chance": 0.125, "warning": "voice, not dialect",
            "calls": {"call_041": {"advisor": {"top3": [{"region": "zh", "p": 0.5}, {"region": "lu", "p": 0.3},
                                                        {"region": "ag", "p": 0.2}]}}}}


def test_normalise_sums_to_one_and_clips():
    q = dm.normalise({"a": 2.0, "b": 1.0, "c": -0.5})
    assert abs(sum(q.values()) - 1.0) < 1e-9 and q["c"] == 0.0 and q["a"] == pytest.approx(0.6667, abs=1e-4)
    with pytest.raises(ValueError):
        dm.normalise({"a": 0.0})


def test_collapse_and_regions():
    lp = dm.collapse_languages({"de": 0.9, "nl": 0.05, "en": 0.05})
    assert lp["other"] == pytest.approx(0.05) and set(lp) == {"de", "fr", "it", "en", "other"}
    rp = dm.language_to_regions(lp)
    assert rp["de_ch"] == pytest.approx(0.9) and rp["other"] == pytest.approx(0.1)
    assert abs(sum(rp.values()) - 1) < 1e-9


def test_build_valid_with_confidence_and_research_gate():
    d = dm.build(LANGID, ["FLEURS test"], RESEARCH)
    adv, cus = d["speakers"]
    assert adv["confidence"] == "high" and cus["confidence"] == "low"
    assert adv["research_dialect"]["top3"][0]["region"] == "zh" and cus["research_dialect"] is None
    at_chance = {**RESEARCH, "cv_ci95": [0.1, 0.3]}
    assert all(s["research_dialect"] is None for s in dm.build(LANGID, [], at_chance)["speakers"])


def test_schema_rejects_bad_role_bad_sum_and_unknown_language():
    good = dm.build(LANGID, [], None)
    DialectEstimate.from_dict(good)
    for mutate in (lambda d: d["speakers"][0].update(role="unknown"),
                   lambda d: d["speakers"][0]["language_probs"].update(de=0.5),
                   lambda d: d["speakers"][0]["language_probs"].update(xx=0.0),
                   lambda d: d["speakers"].append(copy.deepcopy(d["speakers"][0]))):
        d = copy.deepcopy(good)
        mutate(d)
        with pytest.raises(SchemaError):
            DialectEstimate.from_dict(d)


def test_research_block_needs_ci_above_chance():
    d = dm.build(LANGID, [], RESEARCH)
    d["speakers"][0]["research_dialect"]["cv_ci95"] = [0.1, 0.3]
    with pytest.raises(SchemaError):
        DialectEstimate.from_dict(d)


def test_pipeline_never_imports_dialect_code():
    import re
    imp = re.compile(r"^\s*(from|import)\s.*dialect_map|open\(.*dialect_regions", re.M)
    for p in [*(ROOT / "pipeline").rglob("*.py"), ROOT / "run.py"]:
        assert not imp.search(p.read_text(encoding="utf-8")), p


def test_dialect_map_leaves_decision_files_unchanged(tmp_path):
    import hashlib
    run = tmp_path / "run"
    (run / "results").mkdir(parents=True)
    (run / "judge").mkdir()
    for rel, body in (("results.json", {"calls": []}), ("results/call_041.json", {"decision": "alarm"}),
                      ("judge/call_041.json", {"risk": 0.9})):
        (run / rel).write_text(json.dumps(body))
    sha = lambda: {p.relative_to(run).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
                   for p in sorted(run.rglob("*.json"))}
    before = sha()
    lid = tmp_path / "langid"
    lid.mkdir()
    (lid / "call_041.json").write_text(json.dumps(LANGID))
    assert dm.main(["--langid-dir", str(lid), "--out", str(run.parent / "dialect"),
                    "--validation", str(tmp_path / "none.json")]) == 0
    assert sha() == before
    DialectEstimate.from_dict(json.loads((run.parent / "dialect" / "call_041.json").read_text()))


def test_web_region_table_mirrors_config():
    import re
    ts = (ROOT / "web" / "components" / "audio" / "swiss-map.tsx").read_text(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "dialect_regions.json").read_text(encoding="utf-8"))
    for region, v in cfg["language_regions"].items():
        m = re.search(rf'{region}: {{ label: "[^"]+", cantons: \[([^\]]+)\]', ts)
        assert m, region
        assert re.findall(r'"([A-Z]{2})"', m.group(1)) == v["cantons"], region
    bi = re.search(r"BILINGUAL_CANTONS = \[([^\]]+)\]", ts).group(1)
    assert re.findall(r'"([A-Z]{2})"', bi) == list(cfg["bilingual_cantons"])
    cantons = {c for v in cfg["language_regions"].values() for c in v["cantons"]}
    assert len(cantons) == 26


def test_langid_windows_and_weighted_average():
    import numpy as np
    import pod_langid as pl
    audio = np.zeros(pl.SR * 100, dtype=np.float32)
    ws = pl.windows(audio, [(0.0, 0.5), (1.0, 41.0), (50.0, 75.0)])     # the 0.5 s turn is dropped
    assert [round(len(w) / pl.SR) for w in ws] == [30, 30, 5]
    avg = pl.average([{"de": 1.0}, {"de": 0.5, "fr": 0.5}], [30.0, 10.0])
    assert avg == pytest.approx({"de": 0.875, "fr": 0.125})


def test_research_cv_is_grouped_and_reports_chance():
    import numpy as np
    import dialect_research as dr
    rng = np.random.default_rng(0)
    y = np.repeat(np.array(list("abcdefgh")), 20)
    g = np.tile(np.arange(20), 8)                              # 20 parallel sentences per class
    noise = dr.cv(rng.normal(size=(160, 16)), y, g)
    assert noise["chance"] == 0.125 and noise["ci95"][0] <= 0.125 + 0.1     # pure noise is not shown as skill
    sep = dr.cv(np.eye(8)[np.searchsorted(sorted(set(y)), y)] * 5 + rng.normal(scale=0.1, size=(160, 8)), y, g)
    assert sep["accuracy"] > 0.95 and sep["ci95"][0] > sep["chance"]


def test_langid_validation_accuracy_and_wilson(tmp_path):
    import langid_validation as lv
    assert lv.wilson(0, 0) == [0.0, 0.0]
    lo, hi = lv.wilson(48, 50)
    assert 0.85 < lo < 0.96 < hi <= 1.0
    clips = {"clips": [{"set": "FLEURS test", "lang": "fr", "pred": p, "p_gold": 0.9, "duration_s": 10.0}
                       for p in ("fr", "fr", "fr", "it")]}
    f = tmp_path / "fleurs.json"
    f.write_text(json.dumps(clips))
    s = lv.clip_set(f)["FLEURS test"]["fr"]
    assert (s["n"], s["correct"], s["accuracy"]) == (4, 3, 0.75) and s["predicted"] == {"fr": 3, "it": 1}
    calls = tmp_path / "calls"
    calls.mkdir()
    (calls / "call_001.json").write_text(json.dumps({"speakers": {"advisor": {"probs": {"de": 0.9, "en": 0.1}},
                                                                   "customer": {"probs": {"nl": 0.6, "de": 0.4}}}}))
    c = lv.calls(calls)
    assert (c["speakers"], c["de_on_top"], c["top_language"]) == (2, 1, {"de": 1, "nl": 1})
