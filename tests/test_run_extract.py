"""scripts/run_extract.py tuning splits and parallel workers. No network: the client and extraction are faked."""
import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import run_extract as rx  # noqa: E402
from pipeline.schemas import RunResult, Transcript, TranscriptSegment  # noqa: E402

SPLITS = {"splits": {"dev": {"call_ids": ["call_001", "call_002", "call_003"]},
                     "holdout": {"call_ids": ["call_009"]},
                     "test": {"call_ids": ["call_005", "call_006"]}}}


@pytest.fixture
def splits(tmp_path, monkeypatch):
    p = tmp_path / "splits.json"
    p.write_text(json.dumps(SPLITS), encoding="utf-8")
    monkeypatch.setattr(rx, "SPLITS_FILE", p)
    return p


def test_tune_is_dev_plus_test_never_holdout(splits):
    assert rx.split_call_ids("tune") == ["call_001", "call_002", "call_003", "call_005", "call_006"]
    assert rx.split_call_ids("test") == ["call_005", "call_006"]
    assert "holdout" not in rx.TUNING_SPLITS


@pytest.mark.parametrize("argv", [["--split", "test"], ["--split", "tune"], ["--split", "holdout"]])
def test_test_needs_allow_flag_and_holdout_refused(argv, splits, monkeypatch):
    monkeypatch.setattr(rx, "run", lambda *a, **k: pytest.fail("must refuse before running"))
    with pytest.raises(SystemExit) as e:
        rx.main(argv)
    assert e.value.code == 2


class FakeClient:
    model, model_revision = "fake-model", "r1"

    class spec:
        name = "fake"

    def probe(self):
        return {}

    def version_info(self):
        return {"llm": "fake-model@r1", "provider": "fake", "self_hosted": True}


def test_workers_keep_split_order(splits, tmp_path, monkeypatch):
    monkeypatch.setattr(rx, "PRED_DIR", tmp_path / "pred")
    monkeypatch.setattr(rx, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setattr(rx, "TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(rx.llm, "get_client", lambda *a, **k: FakeClient())
    monkeypatch.setattr(rx, "load_transcript", lambda cid, source: Transcript(
        cid, "reference", [TranscriptSegment("T001", "advisor", "Grüezi, Bank Lindenhof.")]))
    delays = {"call_001": 0.15, "call_002": 0.0, "call_003": 0.05, "call_005": 0.1, "call_006": 0.0}

    def fake_extract(t, client, report):
        time.sleep(delays[t.call_id])                    # finish out of order
        if t.call_id == "call_003":
            raise rx.llm.LLMError("truncated")
        return []

    monkeypatch.setattr(rx.ex, "extract_facts", fake_extract)
    pred, stats = rx.run("tune", "reference", None, None, None, workers=4)
    run = RunResult.from_dict(json.loads(pred.read_text(encoding="utf-8")))
    assert [c.call_id for c in run.calls] == rx.split_call_ids("tune")
    assert [r["call_id"] for r in stats["per_call"]] == rx.split_call_ids("tune")
    failed = {c.call_id: c for c in run.calls if c.stage_errors}
    assert list(failed) == ["call_003"] and failed["call_003"].decision == "review"    # never silently no_alert
    assert stats["summary"]["calls_failed"] == 1 and "_reference_tune" in pred.name
