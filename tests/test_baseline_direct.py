"""Milestone 2: scripts/baseline_direct.py prompt hygiene, response parsing, caching (mock only, no network)."""
import builtins
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import baseline_direct as bd  # noqa: E402
from pipeline import evaluate as ev  # noqa: E402
from pipeline import reference as ref  # noqa: E402
from pipeline.schemas import RunResult, Versions  # noqa: E402

needs_data = pytest.mark.skipif(not (ev.EVAL_MANIFEST.is_file() and ev.SPLITS_FILE.is_file()
                                     and ref.REFERENCE_FILE.is_file()),
                                reason="run scripts/prepare_data.py first")
V = Versions(llm="m@r", prompt=bd.PROMPT_VERSION)


def test_valid_response():
    raw = 'Sure: {"decision": "alarm", "criterion": "insider_trading", "risk": 0.95, "reason": "x", ' \
          '"evidence": [{"segment_id": "T012", "speaker": "customer", "quote": "nöd öffentlich"}]} done'
    r = bd.to_call_result("call_001", raw, V)
    assert r.decision == "alarm" and r.risk_score == 0.95 and r.confidence is None
    assert r.findings[0].criterion == "insider_trading"
    assert r.findings[0].evidence[0].segment_ids == ["T012"]


@pytest.mark.parametrize("raw", ["", "no json here", '{"decision": "maybe"}', "[1, 2]"])
def test_unusable_response_goes_to_review_with_stage_error(raw):
    r = bd.to_call_result("call_001", raw, V)
    assert r.decision == "review" and r.stage_errors and r.stage_errors[0].stage == "baseline_llm"


def test_unknown_criterion_and_missing_risk():
    r = bd.to_call_result("c", '{"decision": "review", "criterion": "fraud", "evidence": []}', V)
    assert r.findings[0].criterion == "other" and r.risk_score == bd.DEFAULT_RISK["review"]


@needs_data
def test_prompt_contains_no_labels_or_names():
    man = json.loads(ev.EVAL_MANIFEST.read_text(encoding="utf-8"))
    for cid, c in man["calls"].items():
        user = bd.build_messages(ref.reference_transcript(cid))[-1]["content"]
        d = man["dialogues"][c["dialogue_id"]]
        for leak in ("Stufe", "Bearbeitung", "Sollbewertung", "alarm", "no_alert", "review", cid,
                     c["dialogue_id"], Path(c["original_filename"]).stem):
            assert leak not in user, (cid, leak)
        assert (d["reasoning"] or "@@") not in user


@needs_data
def test_mock_run_writes_valid_predictions_and_caches(tmp_path, monkeypatch):
    out, stats = bd.run("dev", "mock", out_dir=tmp_path / "pred", cache_dir=tmp_path / "cache", limit=6)
    rr = RunResult.from_dict(json.loads(out.read_text(encoding="utf-8")))
    assert rr.provider.startswith("MOCK") and rr.run_id.startswith("baseline_direct_MOCK")
    assert any("MOCK" in n for n in rr.notes) and len(rr.calls) == 6
    # second run must be served entirely from the cache
    monkeypatch.setattr(bd.MockProvider, "chat", lambda *a, **k: pytest.fail("cache miss"))
    _, stats2 = bd.run("dev", "mock", out_dir=tmp_path / "pred", cache_dir=tmp_path / "cache", limit=6)
    assert stats2["cache_hits"] == 6 and stats2["llm_requests"] == 0


@needs_data
def test_mock_baseline_never_opens_evaluation_manifest(tmp_path, monkeypatch):
    def guard(opener):
        def wrapped(file, *a, **k):
            if Path(file).name == "evaluation.json":
                pytest.fail(f"baseline opened the label manifest: {file}")
            return opener(file, *a, **k)
        return wrapped
    monkeypatch.setattr(builtins, "open", guard(builtins.open))
    monkeypatch.setattr(Path, "open", guard(Path.open))
    out, stats = bd.run("dev", "mock", out_dir=tmp_path / "pred", cache_dir=tmp_path / "cache")
    assert stats["calls"] == len(json.loads(ev.SPLITS_FILE.read_text(encoding="utf-8"))["splits"]["dev"]["call_ids"])


def test_baseline_does_not_import_evaluate():
    src = (REPO_ROOT / "scripts" / "baseline_direct.py").read_text(encoding="utf-8")
    imports = re.compile(r"^\s*(from\s+pipeline\.evaluate\b|from\s+pipeline\s+import\s+.*\bevaluate\b|"
                         r"import\s+pipeline\.evaluate\b)", re.M)
    assert not imports.search(src)
    # fresh interpreter: importing the baseline must not pull in pipeline.evaluate transitively
    code = ("import sys; sys.path.insert(0, 'scripts'); import baseline_direct; "
            "print('pipeline.evaluate' in sys.modules)")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"
