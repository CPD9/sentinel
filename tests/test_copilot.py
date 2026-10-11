"""web/scripts/copilot.py: streamed claim parsing, evidence validation, retry, patterns, label isolation."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from pipeline.schemas import Transcript, TranscriptSegment

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web" / "scripts" / "copilot.py"
spec = importlib.util.spec_from_file_location("copilot", SCRIPT)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def tr(call_id="call_001") -> Transcript:
    segs = [TranscriptSegment("S0001", "unknown", "Grüezi, wie chan ich Ihne hälfe?", 0.0, 2.0),
            TranscriptSegment("S0002", "customer", "Mini Schwöschter schafft i de Finanzabteilig.", 2.5, 5.0),
            TranscriptSegment("S0003", "advisor", "Den Auftrag nehme ich so nicht entgegen.", 5.5, 8.0)]
    return Transcript(call_id=call_id, mode="asr", segments=segs, duration_s=10.0)


def claim(text, seg, quote, call=None):
    return cp.to_parsed({"claim": text, "segment_id": seg, "quote": quote, **({"call_id": call} if call else {})})


def test_verbatim_quote_is_kept_with_timestamps():
    res = cp.check_line(claim("The advisor refused.", "S0003", "Den Auftrag nehme ich so nicht"), {"call_001": tr()}, "call_001", 1)
    c = res["ok"]["citations"][0]
    assert (c["segment_id"], c["start_s"], c["end_s"], c["speaker"]) == ("S0003", 5.5, 8.0, "advisor")


@pytest.mark.parametrize("parsed,reason", [
    (claim("Paraphrase.", "S0003", "The advisor said no to the order"), "quote not in cited segments"),
    (claim("Made up id.", "S0099", "Den Auftrag nehme ich"), "unknown segment id"),
    (claim("No quote.", "S0003", ""), "uncited"),
    (claim("", "S0003", "Den Auftrag nehme ich"), "uncited"),
    ({"text": "Uncited claim.", "cites": []}, "uncited"),
])
def test_unverifiable_claims_are_dropped(parsed, reason):
    assert cp.check_line(parsed, {"call_001": tr()}, "call_001", 1) == {"drop": reason}


def test_cross_call_citation_is_checked_against_that_call():
    ts = {"call_001": tr("call_001"), "call_002": tr("call_002")}
    ok = cp.check_line(claim("Sister works there.", "S0002", "Schwöschter schafft i de Finanzabteilig", "call_002"), ts, None, 1)
    assert ok["ok"]["citations"][0]["call_id"] == "call_002"
    assert cp.check_line(claim("x", "S0002", "Schwöschter schafft", "call_999"), ts, None, 1) == {"drop": "unknown call"}


def test_scanner_yields_claims_as_they_complete():
    reply = json.dumps({"in_call": True, "claims": [{"claim": "A {b}", "segment_id": "S0001", "quote": "q1"},
                                                     {"claim": "C", "segment_id": "S0002", "quote": "q2"}]})
    scan, got = cp.ClaimScanner(), []
    for i in range(0, len(reply), 7):
        got += scan.feed(reply[i:i + 7])
    assert [g["segment_id"] for g in got] == ["S0001", "S0002"]


class FakeClient:
    """Stands in for OpenAICompatClient: replies are canned, one per request."""
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def stream(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        for i in range(0, len(reply), 5):
            yield reply[i:i + 5]


@pytest.fixture
def events(monkeypatch):
    out = []
    monkeypatch.setattr(cp, "emit", out.append)
    return out


def run(monkeypatch, replies):
    fake = FakeClient(replies)
    monkeypatch.setattr(cp, "stream_reply", lambda client, messages, schema: fake.stream(messages))
    stats = cp.answer(fake, [{"role": "user", "content": "q"}], {"call_001": tr()}, "call_001", cp.claim_schema(False))
    return fake, stats


def test_answer_streams_valid_claims_and_drops_the_rest(monkeypatch, events):
    reply = json.dumps({"in_call": True, "claims": [
        {"claim": "Refused.", "segment_id": "S0003", "quote": "Den Auftrag nehme ich so nicht entgegen."},
        {"claim": "Invented.", "segment_id": "S0001", "quote": "Kaufen Sie die Aktie jetzt"}]})
    fake, stats = run(monkeypatch, [reply])
    assert [e["type"] for e in events] == ["claim", "dropped"]
    assert stats == {"kept": 1, "dropped": 1, "retried": 0} and len(fake.calls) == 1


def test_all_claims_failing_triggers_one_retry_then_not_in_call(monkeypatch, events):
    bad = json.dumps({"in_call": True, "claims": [{"claim": "x", "segment_id": "S0001", "quote": "nothing like it"}]})
    fake, stats = run(monkeypatch, [bad, bad])
    assert len(fake.calls) == 2 and "evidence check" in fake.calls[1][-1]["content"]
    assert [e["type"] for e in events] == ["dropped", "retry", "dropped", "not_in_call"]
    assert stats["kept"] == 0


def test_model_saying_not_in_call_is_not_retried(monkeypatch, events):
    fake, _ = run(monkeypatch, [json.dumps({"in_call": False, "claims": []})])
    assert len(fake.calls) == 1 and events == [{"type": "not_in_call"}]


def test_history_carries_only_validated_claims():
    msgs = cp.messages_for("sys", "ctx", "Who said it?", [
        {"q": "Why?", "claims": [{"claim": "Refused.", "segment_id": "S0003", "quote": "Den Auftrag", "extra": "dropped"}]}])
    prior = json.loads(msgs[-2]["content"])
    assert msgs[-3]["content"] == "Why?" and prior["claims"] == [{"claim": "Refused.", "segment_id": "S0003", "quote": "Den Auftrag"}]


def write(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), "utf-8")


def test_patterns_find_entities_and_shared_phrases(tmp_path):
    run_dir, art = tmp_path / "run", tmp_path / "art"
    write(run_dir / "results.json", {"mode": "asr"})
    for cid, decision in (("call_001", "alarm"), ("call_002", "review"), ("call_003", "no_alert"),
                          ("call_004", "no_alert"), ("call_005", "no_alert"), ("call_006", "no_alert"),
                          ("call_007", "no_alert"), ("call_008", "no_alert")):
        write(run_dir / "results" / f"{cid}.json", {"call_id": cid, "decision": decision, "risk_score": 0.5})
        t = tr(cid)
        write(run_dir / "transcripts" / f"{cid}.json", {"mode": "asr", "segments": [s.__dict__ for s in t.segments]})
        facts = [{"fact_id": "f001", "speaker": "customer", "act": "disclose", "info_type": "nonpublic_info",
                  "segment_ids": ["S0002"], "quote": "Mini Schwöschter schafft i de Finanzabteilig", "valid": True,
                  "recipient_third_party": True}] if cid in ("call_001", "call_002") else []
        write(run_dir / "traces" / f"{cid}.json", {"facts": facts, "rules": []})
        write(run_dir / "judge" / f"{cid}.json", {"decision": decision, "criterion": "insider_trading" if decision == "alarm" else "other",
                                                  "risk": 0.9, "reason": "r", "citations": []})
    p = cp.patterns(cp.Store(art, run_dir))
    assert [r["entity"] for r in p["criteria"]] == ["insider_trading"]
    fam = next(r for r in p["recipients"] if r["entity"] == "Family member")
    assert fam["n_calls"] == 2 and fam["hits"][0]["start_s"] == 2.5
    assert any(ph["phrase"] == "mini schwöschter schafft i" for ph in p["phrases"])


def test_label_isolation():
    src = SCRIPT.read_text("utf-8")
    assert "evaluation.json" not in src.replace("Never evaluation.json", "")
    assert "Stufe" not in src
