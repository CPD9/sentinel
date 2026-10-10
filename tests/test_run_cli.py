import json

import run as cli
from pipeline import stages
from tests.test_pipeline_run import asr_transcript, make_wav


def test_folder_run_neutral_ids_and_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(stages, "run_analysis", lambda *a, **k: (None, [], False))
    monkeypatch.setattr(stages, "run_asr", lambda audio, cid, **k: (asr_transcript(cid), []))
    monkeypatch.setattr(cli, "INFERENCE", tmp_path / "none.json")
    folder = tmp_path / "wavs"
    folder.mkdir()
    make_wav(folder / "Stufe3_geheim.wav")
    make_wav(folder / "other.wav")
    out = tmp_path / "out"
    monkeypatch.setattr(cli, "PRED_DIR", tmp_path / "pred")
    assert cli.main([str(folder), "--no-llm", "--out", str(out), "--run-id", "t", "--predictions"]) == 0
    res = json.loads((out / "results.json").read_text())
    assert [c["call_id"] for c in res["calls"]] == ["call_x001", "call_x002"]
    assert "Stufe3" not in json.dumps(res)
    assert (out / "results" / "call_x001.json").is_file() and (tmp_path / "pred" / "t.json").is_file()
    assert json.loads((out / "id_map.json").read_text())["map"]["Stufe3_geheim.wav"] == "call_x001"
    assert res["provider"].startswith("keywords+rules") and res["notes"][0].startswith("NO LLM")


def test_test_split_is_locked(monkeypatch):
    import pytest
    with pytest.raises(SystemExit):
        cli.plan_jobs(None, "test", allow_test=False)
