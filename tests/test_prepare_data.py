"""Milestone 1 checks for scripts/prepare_data.py.

The script runs once per session into a temporary directory against the real data under data/
(or $DATA_DIR). Tests are skipped when the data is not present (e.g. in CI).
"""
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import prepare_data  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
SOURCES = {name: sub for name, sub, _policy, _claim in prepare_data.SOURCES}

pytestmark = pytest.mark.skipif(
    not all((DATA_DIR / sub / "Audio").is_dir() for sub in SOURCES.values()),
    reason=f"case data not found under {DATA_DIR}",
)


def fingerprint(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns, st.st_mode,
                                             hashlib.sha256(p.read_bytes()).hexdigest())
    return out


@pytest.fixture(scope="session")
def run(tmp_path_factory):
    before = fingerprint(DATA_DIR)
    out = tmp_path_factory.mktemp("artifacts")
    prepare_data.build(DATA_DIR, out)
    after = fingerprint(DATA_DIR)
    load = lambda rel: json.loads((out / rel).read_text(encoding="utf-8"))  # noqa: E731
    return {
        "out": out,
        "before": before,
        "after": after,
        "inference": load("manifests/inference.json"),
        "evaluation": load("manifests/evaluation.json"),
        "splits": load("splits/dialogue_splits.json"),
        "report": load("manifests/data_report.json"),
    }


def original_audio() -> list[Path]:
    return sorted(p for sub in SOURCES.values() for p in (DATA_DIR / sub / "Audio").glob("*.wav"))


# --------------------------------------------------------------------------- every audio file once

def test_every_audio_file_exactly_once(run):
    files = original_audio()
    calls = run["evaluation"]["calls"]
    mapped = [(REPO_ROOT / c["original_audio_path"]).resolve() for c in calls.values()]
    assert len(mapped) == len(set(mapped)) == len(files)
    assert {p.resolve() for p in files} == set(mapped)

    inf_ids = [c["call_id"] for c in run["inference"]["calls"]]
    assert len(inf_ids) == len(set(inf_ids)) == len(files)
    assert set(inf_ids) == set(calls)


def test_neutral_audio_copies_match_originals(run):
    by_name = {p.name: p for p in original_audio()}
    for c in run["inference"]["calls"]:
        copy = Path(c["audio_path"])
        copy = copy if copy.is_absolute() else REPO_ROOT / copy
        assert copy.name == f"{c['call_id']}.wav"
        ev = run["evaluation"]["calls"][c["call_id"]]
        digest = hashlib.sha256(copy.read_bytes()).hexdigest()
        assert digest == ev["sha256"]
        assert digest == hashlib.sha256(by_name[ev["original_filename"]].read_bytes()).hexdigest()
        assert c["duration_s"] > 0


def test_no_issues_and_readme_counts(run):
    assert run["report"]["issues"] == []
    for name, chk in run["report"]["readme_check"].items():
        assert chk["found_recordings"] == chk["readme_recordings"], name
        assert chk["found_dialogues"] == chk["readme_dialogues"], name


# --------------------------------------------------------------------------- dialogue mapping

def test_call_to_dialogue_mapping(run):
    ev = run["evaluation"]
    for call_id, c in ev["calls"].items():
        m = prepare_data.AUDIO_RE.match(c["original_filename"])
        assert m, c["original_filename"]
        assert c["dialogue_id"] == m["dlg"]
        assert c["stufe"] == int(m["stufe"])
        assert c["variant"] == prepare_data.TAKE_VARIANT[m["take"]]
        d = ev["dialogues"][c["dialogue_id"]]
        assert call_id in d["call_ids"]
        assert d["label"] == c["label"] in {"alarm", "no_alert", "review"}
        assert Path(d["transcript_path"]).name == f"Stufe{d['stufe']}_{d['dialogue_id']}.txt"
        assert (REPO_ROOT / d["transcript_path"]).exists() or Path(d["transcript_path"]).exists()


def test_each_dialogue_has_expected_recordings(run):
    ev = run["evaluation"]
    assert sum(len(d["call_ids"]) for d in ev["dialogues"].values()) == len(ev["calls"])
    for dlg, d in ev["dialogues"].items():
        variants = sorted(ev["calls"][c]["variant"] for c in d["call_ids"])
        if d["recording"] == "human":
            assert variants == ["unspecified"], dlg
        else:
            assert variants == ["clean", "noisy"], dlg
        assert d["reasoning"], dlg
        assert d["key_passages"], dlg
        assert all(p["text"] for p in d["key_passages"]), dlg


# --------------------------------------------------------------------------- splits

def split_of_calls(splits) -> dict:
    where = defaultdict(list)
    for name, s in splits["splits"].items():
        for c in s["call_ids"]:
            where[c].append(name)
    return where


def test_every_call_in_exactly_one_split(run):
    where = split_of_calls(run["splits"])
    assert set(where) == set(run["evaluation"]["calls"])
    assert all(len(v) == 1 for v in where.values())


def test_no_dialogue_in_two_splits(run):
    where = split_of_calls(run["splits"])
    per_dialogue = defaultdict(set)
    for call_id, c in run["evaluation"]["calls"].items():
        per_dialogue[c["dialogue_id"]].update(where[call_id])
    assert all(len(s) == 1 for s in per_dialogue.values()), per_dialogue


def test_twins_stay_together(run):
    ev, where = run["evaluation"], split_of_calls(run["splits"])
    group_of_call = {c: g["group_id"] for s in run["splits"]["splits"].values()
                     for g in s["groups"] for c in g["call_ids"]}
    # independent definition of twins: Stufe2 dialogues with the same title in the same source
    by_title = defaultdict(list)
    for dlg, d in ev["dialogues"].items():
        if d["stufe"] == 2:
            by_title[(d["source"], d["title"])].append(dlg)
    assert by_title and all(len(v) == 2 for v in by_title.values())
    for pair in by_title.values():
        calls = [c for dlg in pair for c in ev["dialogues"][dlg]["call_ids"]]
        assert len({where[c][0] for c in calls}) == 1, pair
        assert len({group_of_call[c] for c in calls}) == 1, pair
        assert sorted(ev["dialogues"][pair[0]]["twin_dialogue_ids"]) == [pair[1]]


def test_test30_is_locked_test_split(run):
    ev, where = run["evaluation"], split_of_calls(run["splits"])
    for call_id, c in ev["calls"].items():
        assert (where[call_id][0] == "test") == (c["source"] == "test30"), call_id


def test_holdout_is_stratified(run):
    report = run["report"]
    for s in report["split_stratification"]:
        if s["units"] >= 2:
            assert s["holdout_units"] >= 1 and s["dev_units"] >= 1, s
    hold = report["split_summary"]["holdout"]["dialogues"]
    dev = report["split_summary"]["dev"]["dialogues"]
    assert 0.2 <= hold / (hold + dev) <= 0.4


def test_splits_are_deterministic(run, tmp_path):
    prepare_data.build(DATA_DIR, tmp_path)
    again = json.loads((tmp_path / "splits/dialogue_splits.json").read_text(encoding="utf-8"))
    assert again == run["splits"]
    ev = json.loads((tmp_path / "manifests/evaluation.json").read_text(encoding="utf-8"))
    assert {k: v["original_filename"] for k, v in ev["calls"].items()} == \
           {k: v["original_filename"] for k, v in run["evaluation"]["calls"].items()}


# --------------------------------------------------------------------------- label isolation

def forbidden_tokens(evaluation) -> list[str]:
    tokens = {"Stufe", "stufe", "alarm", "no_alert", "review", "label", "Bearbeitung", "reasoning",
              "Begründung", "dialogue", "transcript", "Transkript", "Skript", "passage", "Beleg",
              "original", "case/", "test30", "split", "holdout"}
    for c in evaluation["calls"].values():
        tokens.add(c["original_filename"])
        tokens.add(Path(c["original_filename"]).stem)
        tokens.add(c["dialogue_id"])
    for d in evaluation["dialogues"].values():
        tokens.add(d["title"])
    return sorted(tokens)


def test_inference_manifest_has_no_labels_or_names(run):
    text = (run["out"] / "manifests/inference.json").read_text(encoding="utf-8")
    hits = [t for t in forbidden_tokens(run["evaluation"]) if t in text]
    assert hits == []
    assert not re.search(r"\b[CDM]\d{2}\b|-K[1-4]\b|\bK[1-4]\b", text)
    allowed = {"call_id", "audio_path", "variant", "duration_s", "sample_rate", "channels"}
    assert set(run["inference"]) == {"schema_version", "calls"}
    for c in run["inference"]["calls"]:
        assert set(c) == allowed
        assert re.fullmatch(r"call_\d{3}", c["call_id"])
        assert c["variant"] in {"clean", "noisy", "unspecified"}
    assert sorted(p.name for p in (run["out"] / "audio").iterdir()) == \
           sorted(f"{c['call_id']}.wav" for c in run["inference"]["calls"])


def test_split_file_has_no_labels_or_names(run):
    text = (run["out"] / "splits/dialogue_splits.json").read_text(encoding="utf-8")
    allowed_here = {"split", "holdout", "test30"}  # split names and policy text are fine here
    hits = [t for t in forbidden_tokens(run["evaluation"]) if t in text and t not in allowed_here]
    assert hits == []


def test_call_ids_do_not_follow_file_order(run):
    names = [run["evaluation"]["calls"][c]["original_filename"] for c in sorted(run["evaluation"]["calls"])]
    assert names != sorted(names)


# --------------------------------------------------------------------------- original data untouched

def test_original_data_untouched(run):
    assert run["before"] == run["after"]
    assert run["before"]  # fingerprint actually covered files


def test_refuses_to_write_inside_data(tmp_path):
    with pytest.raises(SystemExit):
        prepare_data.build(DATA_DIR, DATA_DIR / "artifacts")
