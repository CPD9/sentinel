"""Milestone 3: ASR metrics, label-free benchmark call selection, SwissDial sampler (no GPU, no models)."""
import ast
import io
import json
import re
import sys
import tarfile
from pathlib import Path

import pytest

from pipeline import asr_metrics as m

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import prepare_swissdial  # noqa: E402

TERMS = m.keyword_terms({"keywords": [
    {"id": "K01", "de": ["nicht öffentlich"], "gsw": ["nöd öffentlich"]},
    {"id": "K10", "de": ["PIN", "Passwort"], "gsw": ["PIN", "Passwort"]},
    {"id": "K99", "de": ["aus"], "gsw": ["us"], "enabled": False},
]})


def test_normalise():
    assert m.normalise("Grüezi, Rosenau-Bank!  Strasse ß") == "grüezi rosenau bank strasse ss"
    assert m.normalise("«Parasite» isch's") == "parasite ischs"


def test_wer_cer():
    assert m.wer("a b c d", "a b c d") == 0.0
    assert m.wer("a b c d", "a x c") == 0.5            # 1 substitution + 1 deletion
    assert m.wer("Hallo, Welt", "hallo welt") == 0.0   # normalised
    assert m.wer("", "x") is None and m.cer("", "") is None
    assert m.wer("a b", "") == 1.0
    assert m.cer("abcd", "abed") == 0.25
    assert m.error_counts("a b", "a b c", "word") == (1, 2)


def test_keyword_terms_skip_disabled():
    assert set(TERMS) == {"K01", "K10"}
    assert TERMS["K10"] == ["passwort", "pin"]


def test_keyword_recall_counts_either_variant():
    ref = "Das isch nöd öffentlich. Gänd Sie mir de PIN."
    hyp = "Das ist nicht öffentlich. Geben Sie mir die Pin."   # Standard German output still counts
    r = m.keyword_recall(ref, hyp, TERMS)
    assert r["presence_total"] == 2 and r["presence_hits"] == 2 and r["missed"] == []


def test_keyword_recall_fuzzy_but_short_terms_exact():
    r = m.keyword_recall("nöd öffentlich", "nöd öffentli", TERMS)
    assert r["found"] == ["K01"]                                    # fuzzy multi-word match
    r = m.keyword_recall("de PIN bitte", "de pinn bitte", TERMS)
    assert r["missed"] == ["K10"]                                   # PIN must match exactly
    assert m.count_term("pinsel", "pin") == 0                       # no partial-word hits


def test_keyword_occurrence_recall():
    r = m.keyword_recall("pin pin pin", "pin", TERMS)
    assert (r["occurrence_hits"], r["occurrence_total"]) == (1, 3)
    assert (r["presence_hits"], r["presence_total"]) == (1, 1)


def test_timestamp_sanity():
    good = [{"start": 0.5, "end": 2.0, "words": [{"start": 0.5, "end": 1.0}]},
            {"start": 2.1, "end": 5.0, "words": [{"start": 2.2, "end": 4.9}]}]
    s = m.timestamp_sanity(good, 6.0)
    assert s["ok"] and s["n_overlaps"] == 0 and s["max_gap_s"] == 1.0 and 0.7 < s["coverage_frac"] < 0.8
    bad = [{"start": 3.0, "end": 9.0}, {"start": 1.0, "end": 2.0}]
    s = m.timestamp_sanity(bad, 6.0)
    assert not s["ok"] and not s["monotonic"] and s["valid_span_frac"] == 0.5
    assert m.timestamp_sanity([], 6.0)["ok"] is False


# --------------------------------------------------------------------------- benchmark selection

@pytest.fixture(scope="module")
def bench():
    pytest.importorskip("faster_whisper")
    import benchmark_asr
    return benchmark_asr


def _toy_manifests():
    splits = {"splits": {
        "dev": {"call_ids": ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"],
                "groups": [{"group_id": "g1", "call_ids": ["c1", "c2"]},
                           {"group_id": "g2", "call_ids": ["c3", "c4", "c5", "c6"]},
                           {"group_id": "g3", "call_ids": ["c7", "c8"]}]},
        "holdout": {"call_ids": ["h1", "h2"], "groups": [{"group_id": "g4", "call_ids": ["h1", "h2"]}]},
        "test": {"call_ids": [], "groups": []}}}
    var = {"c1": "noisy", "c2": "clean", "c3": "clean", "c4": "clean", "c5": "noisy", "c6": "noisy",
           "c7": "clean", "c8": "noisy", "h1": "clean", "h2": "noisy"}
    inference = {c: {"variant": v} for c, v in var.items()}
    script = {"c1": "A", "c2": "A", "c3": "B", "c5": "B", "c4": "C", "c6": "C", "c7": "D", "c8": "D",
              "h1": "E", "h2": "E"}
    reference = {c: [{"segment_id": "T001", "speaker": "advisor", "text": s}] for c, s in script.items()}
    return splits, inference, reference


def test_dialogues_pair_twins_by_script(bench):
    ds = bench.dev_dialogues(*_toy_manifests())
    assert sorted(tuple(d["call_ids"]) for d in ds) == [("c2", "c1"), ("c3", "c5"), ("c4", "c6"), ("c7", "c8")]
    # clean first, noisy second
    assert all(len(d["call_ids"]) == 2 for d in ds)


def test_selection_dev_only_distinct_groups_seeded(bench):
    splits, inf, ref = _toy_manifests()
    sel = bench.select_calls(splits, inf, ref, n_dialogues=3, seed=1)
    assert len(sel) == 3 and len({d["group_id"] for d in sel}) == 3
    calls = [c for d in sel for c in d["call_ids"]]
    assert len(calls) == 6 and not set(calls) & {"h1", "h2"}
    assert sel == bench.select_calls(splits, inf, ref, n_dialogues=3, seed=1)   # deterministic
    assert len(bench.select_calls(splits, inf, ref, all_dev=True)) == 4


def _code_without_docstrings(path: Path) -> str:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
    return ast.unparse(tree)


def test_benchmark_never_reads_labels():
    for f in ("scripts/benchmark_asr.py", "pipeline/asr.py", "pipeline/asr_metrics.py"):
        code = _code_without_docstrings(REPO / f)
        assert not re.search(r"evaluation\.json|EVAL_MANIFEST|original_filename|stufe|'label'", code, re.I), f
    assert "evaluation.json" in (REPO / "scripts" / "report_asr_benchmark.py").read_text()   # the only reader


def test_pick_winner_rule(bench):
    s = lambda kw, w, rtf: {"summary": {"keyword_recall": kw, "wer": w, "rtf": rtf}}  # noqa: E731
    models = {"a": s(0.90, 0.50, 0.1), "b": s(0.895, 0.40, 0.2), "c": s(0.80, 0.10, 0.05),
              "d": {"error": "x", "summary": {}}}
    w = bench.pick_winner(models, None)
    assert w["model"] == "b" and set(w["tied_on_recall"]) == {"a", "b"}
    models["b"]["peak_vram_mb"] = 20000
    assert bench.pick_winner(models, 16000)["model"] == "a"


# --------------------------------------------------------------------------- SwissDial sampler

def _toy_tar(path: Path, dialects=("be", "zh"), ids=range(30), missing=None):
    sentences = [{"id": i, "de": f"Satz {i}", **{f"ch_{d}": f"Satz {d} {i}" for d in dialects}} for i in ids]
    with tarfile.open(path, "w") as t:
        def add(name, data: bytes):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        add("data1.1/README.txt", b"readme")
        add("data1.1/sentences_ch_de_transcribed.json", json.dumps(sentences).encode())
        for d in dialects:
            for i in ids:
                if (d, i) != missing:
                    add(f"data1.1/{d}/ch_{d}_{i:04d}.wav", b"RIFF" + bytes([i]))


def test_swissdial_sampler(tmp_path):
    tar = tmp_path / "data1.1.tar"
    _toy_tar(tar, missing=("zh", 3))
    out = prepare_swissdial.build(tar, tmp_path / "sd", tmp_path / "sd.json", n=5, seed=7)
    assert out["dialects"] == ["be", "zh"] and len(out["utterances"]) == 10
    ids = {d: [u["sentence_id"] for u in out["utterances"] if u["dialect"] == d] for d in out["dialects"]}
    assert ids["be"] == ids["zh"] and 3 not in ids["be"]          # same ids everywhere; incomplete id skipped
    u = out["utterances"][0]
    assert u["ref_de"] == f"Satz {u['sentence_id']}" and u["ref_gsw"] == f"Satz be {u['sentence_id']}"
    assert (tmp_path / "sd" / "data1.1" / "be" / f"ch_be_{u['sentence_id']:04d}.wav").is_file()
    again = prepare_swissdial.build(tar, tmp_path / "sd", tmp_path / "sd.json", n=5, seed=7)
    assert again["sentence_ids"] == out["sentence_ids"]
    with pytest.raises(ValueError):
        prepare_swissdial.build(tar, tmp_path / "sd2", tmp_path / "x.json", n=50, seed=7)
