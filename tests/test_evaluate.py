"""Milestone 2: pipeline/evaluate.py metrics, evidence checks and label isolation."""
import json
import re
import sys
from pathlib import Path

import pytest

from pipeline import evaluate as ev
from pipeline import reference as ref

REPO_ROOT = Path(__file__).resolve().parents[1]
HAVE_MANIFESTS = ev.EVAL_MANIFEST.is_file() and ref.REFERENCE_FILE.is_file() and ev.INFERENCE_MANIFEST.is_file() and ev.SPLITS_FILE.is_file()
needs_data = pytest.mark.skipif(not HAVE_MANIFESTS, reason="run scripts/prepare_data.py first")


def test_metrics_hand_computed():
    gold = ["alarm", "alarm", "review", "no_alert", "no_alert"]
    pred = ["alarm", "review", "review", "alarm", "no_alert"]
    m = ev.metric_block(gold, pred)
    s, e, t = m["strict_alarm"], m["escalation"], m["three_class"]
    assert (s["tp"], s["fp"], s["fn"], s["tn"]) == (1, 1, 1, 2)
    assert s["precision"] == 0.5 and s["recall"] == 0.5
    assert (e["tp"], e["fp"], e["fn"], e["tn"]) == (3, 1, 0, 1)
    assert e["precision"] == 0.75 and e["recall"] == 1.0
    assert t["confusion"]["alarm"] == {"alarm": 1, "review": 1, "no_alert": 0}
    assert t["macro_f1"] == pytest.approx((0.5 + 2 / 3 + 2 / 3) / 3)
    assert t["accuracy"] == pytest.approx(0.6)


def test_undefined_metrics_are_none_not_zero():
    m = ev.metric_block(["no_alert", "no_alert"], ["no_alert", "no_alert"])
    assert m["strict_alarm"]["precision"] is None and m["strict_alarm"]["recall"] is None
    assert m["three_class"]["macro_f1_classes"] == ["no_alert"]
    assert m["three_class"]["macro_f1"] == 1.0


def test_quote_score():
    src = "Si het am Mäntig vo ere Übernahme verzellt. Die Sache isch nöd öffentlich."
    assert ev.quote_score("die sache isch nöd öffentlich", src) == 1.0
    assert ev.quote_score("Die Sach isch nöd öffentlich", src) >= ev.QUOTE_MATCH_THRESHOLD
    assert ev.quote_score("Ich gibe Ihne mis Passwort", src) < ev.QUOTE_MATCH_THRESHOLD
    assert ev.quote_score("", src) == 0.0


def test_asr_mode_evidence_checks(tmp_path):
    import wave
    wav = tmp_path / "s.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\0\0" * 1600)
    segs = {"s1": {"text": "das bliibt under eus", "speaker": "customer"}}
    good = {"segment_ids": ["s1"], "speaker": "customer", "text": "bliibt under eus",
            "start_s": 1.0, "end_s": 3.0, "snippet_path": str(wav)}
    r = ev.check_evidence(good, segs, "asr", duration_s=10.0)
    assert r["valid"] and r["checks"]["snippet_contains_speech"] is None
    bad = {**good, "end_s": 12.0, "snippet_path": str(tmp_path / "missing.wav"), "speaker": "advisor"}
    r = ev.check_evidence(bad, segs, "asr", duration_s=10.0)
    assert not r["valid"]
    assert {k for k, v in r["checks"].items() if v is False} == {"timestamps", "snippet_playable", "speaker_match"}


def test_only_evaluate_reads_labels():
    """Structural label isolation: no other pipeline module or the baseline names the label manifest."""
    offenders = []
    for p in [*sorted((REPO_ROOT / "pipeline").glob("*.py")), REPO_ROOT / "scripts" / "baseline_direct.py"]:
        if p.name == "evaluate.py":
            continue
        if re.search(r"evaluation\.json|EVAL_MANIFEST|Sollbewertung", p.read_text(encoding="utf-8")):
            offenders.append(p.name)
    assert offenders == []


@needs_data
def test_reference_file_matches_scripts():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import prepare_data
    man = json.loads(ev.EVAL_MANIFEST.read_text(encoding="utf-8"))
    for cid in man["calls"]:
        dlg = man["dialogues"][man["calls"][cid]["dialogue_id"]]
        text = (REPO_ROOT / dlg["transcript_path"]).read_text(encoding="utf-8")
        theirs = prepare_data.parse_turns(prepare_data.split_header_body(text)[1])
        ours = ref.reference_transcript(cid)
        assert [(t["segment_id"], t["speaker"], t["text"]) for t in ours] == \
               [(t["turn_id"], t["speaker"], t["text"]) for t in theirs], cid


@needs_data
def test_reference_file_is_label_free():
    man = json.loads(ev.EVAL_MANIFEST.read_text(encoding="utf-8"))
    for cid, c in man["calls"].items():
        turns = ref.reference_transcript(cid)
        assert all(set(t) == {"segment_id", "speaker", "text"} for t in turns)
        blob = json.dumps(turns, ensure_ascii=False)
        d = man["dialogues"][c["dialogue_id"]]
        for leak in ("Stufe", "Bearbeitung", "Sollbewertung", "Begründung", "Testziel",
                     Path(c["original_filename"]).stem, d["reasoning"] or "@@"):
            assert leak not in blob, (cid, leak)


@needs_data
def test_perfect_predictions_score_perfectly(tmp_path):
    man = json.loads(ev.EVAL_MANIFEST.read_text(encoding="utf-8"))
    dev = json.loads(ev.SPLITS_FILE.read_text(encoding="utf-8"))["splits"]["dev"]["call_ids"]
    calls = []
    for cid in dev:
        label = man["calls"][cid]["label"]
        d = man["dialogues"][man["calls"][cid]["dialogue_id"]]
        turns = {t["segment_id"]: t for t in ref.reference_transcript(cid)}
        evidence = [{"segment_ids": [tid], "speaker": turns[tid]["speaker"], "text": turns[tid]["text"],
                     "start_s": None, "end_s": None, "snippet_path": None} for tid in d["evidence_turn_ids"]]
        findings = [] if label == "no_alert" else [{"criterion": "other", "risk": 1.0, "reason": "",
                                                    "evidence": evidence, "counter_evidence": []}]
        calls.append({"call_id": cid, "decision": label, "risk_score": 1.0, "confidence": None,
                      "findings": findings, "narrative": "", "stage_errors": [], "versions": {}})
    pred = tmp_path / "p.json"
    pred.write_text(json.dumps({"schema_version": 1, "run_id": "oracle", "mode": "reference",
                                "system": "test", "provider": "oracle", "created_at": "now", "calls": calls}))
    m = ev.evaluate(pred, "dev")
    assert m["overall"]["three_class"]["macro_f1"] == 1.0
    assert m["overall"]["strict_alarm"]["f1"] == 1.0 and m["overall"]["escalation"]["f1"] == 1.0
    assert m["evidence_validity"]["item_validity_rate"] == 1.0
    assert m["evidence_validity"]["gold_passage_hit_rate"] == 1.0
    assert set(m["breakdown"]["stufe"]) == {"1", "2", "3"}


@needs_data
def test_quality_report_and_score_decisions_on_oracle(tmp_path):
    from pipeline.schemas import QualityReport
    man = json.loads(ev.EVAL_MANIFEST.read_text(encoding="utf-8"))
    hold = json.loads(ev.SPLITS_FILE.read_text(encoding="utf-8"))["splits"]["holdout"]["call_ids"]
    calls = [{"call_id": c, "decision": man["calls"][c]["label"], "risk_score": 0.5, "confidence": 0.9, "findings": [],
              "narrative": "", "stage_errors": [], "versions": {}} for c in hold]
    pred = tmp_path / "p.json"
    pred.write_text(json.dumps({"schema_version": 1, "run_id": "oracle", "mode": "asr", "system": "test",
                                "provider": "oracle", "created_at": "now", "calls": calls}))
    rep = ev.quality_report(pred, "holdout", "final_report", n_resamples=50)
    assert QualityReport.validate(rep) == [] and rep["split"] == "holdout" and rep["overall"]["n"] == len(hold)
    esc = rep["overall"]["escalation"]["f1"]
    assert esc["value"] == 1.0 and esc["ci_low"] == 1.0 and rep["bootstrap"]["unit"] == "dialogue group"
    assert sum(b["n"] for b in rep["reliability"]["bins"]) == len(hold) and set(rep["breakdowns"]) == {"stufe", "variant"}
    s = ev.score_decisions({c["call_id"]: c["decision"] for c in calls})
    assert set(s) == {"all", "holdout"} and s["all"]["three_class"]["accuracy"] == 1.0
