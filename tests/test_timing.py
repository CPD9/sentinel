import json
import sys
from pathlib import Path

import run as cli
from pipeline import asr, stages
from pipeline.timing import TimingCollector, stats
from tests.test_pipeline_run import asr_transcript, make_wav


def test_stats_mean_median_p90():
    s = stats([1.0, 2.0, 3.0, 4.0, 10.0])
    assert s == {"n": 5, "mean": 4.0, "median": 3.0, "p90": 10.0, "min": 1.0, "max": 10.0}
    assert stats([]) == {}


def test_collector_sums_stages_and_records_failures():
    c = TimingCollector()
    c({"event": "stage_finished", "call_id": "call_001", "stage": "asr", "elapsed_s": 1.5})
    c({"event": "stage_failed", "call_id": "call_001", "stage": "judge", "elapsed_s": 0.5, "message": "x"})
    c({"event": "job_finished", "call_id": "call_001", "elapsed_s": 2.2, "decision": "review"})
    r = c.report(wall_s=2.5, workers=1, run_id="t")
    assert r["stage_errors"] == 1 and r["stages"]["asr"]["mean"] == 1.5 and r["per_call_s"]["mean"] == 2.2
    assert r["calls"][0]["failed"] == ["judge"]


def test_run_timings_flag_writes_file_and_leaves_results_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(stages, "run_analysis", lambda *a, **k: (None, [], False))
    monkeypatch.setattr(stages, "run_asr", lambda audio, cid, **k: (asr_transcript(cid), []))
    monkeypatch.setattr(cli, "INFERENCE", tmp_path / "none.json")
    folder = tmp_path / "wavs"
    folder.mkdir()
    make_wav(folder / "a.wav")
    make_wav(folder / "b.wav")
    res = {}
    for flag in ([], ["--timings", str(tmp_path / "t.json")]):
        out = tmp_path / f"out{len(flag)}"
        assert cli.main([str(folder), "--no-llm", "--out", str(out), "--run-id", "t", *flag]) == 0
        body = json.loads((out / "results.json").read_text())
        res[len(flag)] = [(c["call_id"], c["decision"], c["risk_score"]) for c in body["calls"]]
    assert res[0] == res[2]                                   # same decisions with and without --timings
    t = json.loads((tmp_path / "t.json").read_text())
    assert t["calls_n"] == 2 and t["stage_errors"] == 0 and "asr" in t["stages"] and t["wall_s"] > 0


def test_flac_upload_keys_the_cache_by_the_wav_sha(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import pod_asr_folder as paf
    wav = tmp_path / "rec_01.wav"
    make_wav(wav)
    folder = tmp_path / "audio"
    folder.mkdir()
    (folder / "rec_01.flac").write_bytes(b"not the wav bytes")
    shas = tmp_path / "shas.json"
    shas.write_text(json.dumps({"rec_01": asr._sha256(wav)}))
    monkeypatch.setattr(asr, "resolve_model", lambda spec: (tmp_path, "m@rev"))
    monkeypatch.setattr(asr, "load_model", lambda *a: object())
    monkeypatch.setattr(asr, "decode", lambda model, p: {"language": "de", "language_probability": 1.0, "segments": []})
    cache = tmp_path / "cache"
    assert paf.main([str(folder), str(cache), "--shas", str(shas)]) == 0
    want = asr.cache_key(asr._sha256(wav), "m@rev", "cuda", "float16")
    assert [p.stem for p in cache.glob("*.json")] == [want]


def test_organiser_export_rows_and_keyword_ids(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import export_organiser as eo
    bp, bf = eo.keyword_index()
    hits = [{"family": "trade", "term": "Quartalszahlen", "matched_text": "Quartalszahlen", "score": 1.0},
            {"family": "trade", "term": "noch nicht publiziert", "matched_text": "noch nicht publiziert", "score": 0.9},
            {"family": "access", "term": "PIN", "matched_text": "Pin", "score": 1.0}]
    assert eo.keyword_ids(hits, bp, bf) == ["K03", "K10"]                     # fuzzy 0.9 is not verbatim
    alarm = {"call_id": "call_x001", "decision": "alarm", "risk_score": 0.9, "confidence": 0.8, "stage_errors": [],
             "findings": [{"criterion": "insider_trading", "risk": 0.9,
                           "evidence": [{"start_s": 47.8}, {"start_s": 44.9}]}]}
    review = {**alarm, "call_id": "call_x002", "decision": "review", "stage_errors": [{"stage": "judge"}]}
    r1 = eo.row("TEST-02", alarm, {"keyword_hits": hits}, bp, bf)
    r2 = eo.row("TEST-03", review, None, bp, bf)
    assert (r1["alert"], r1["manual_review"], r1["alert_audio_seconds"]) == (True, False, 44.9)
    assert (r2["alert"], r2["manual_review"], r2["alert_audio_seconds"], r2["keyword_ids"]) == (False, True, None, None)
    assert "stage_errors=judge" in r2["notes"]
    run = tmp_path / "run"
    (run / "out").mkdir(parents=True)
    (run / "out" / "results.json").write_text(json.dumps({"run_id": "t", "calls": [alarm, review]}))
    (run / "out" / "id_map.json").write_text(json.dumps({"map": {"TEST-02.wav": "call_x001", "TEST-03.wav": "call_x002"}}))
    eo.export(run, tmp_path / "exp")
    lines = (tmp_path / "exp" / "Ergebnisse.jsonl").read_text().splitlines()
    assert [json.loads(x)["clip_id"] for x in lines] == ["TEST-02", "TEST-03"]
    assert (tmp_path / "exp" / "Ergebnisse.csv").read_text().splitlines()[0] == ",".join(eo.FIELDS)
