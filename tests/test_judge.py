"""pipeline/judge.py: ASR prompt, citation validation, caching, unusable answers. No network: fake client."""
import json
from dataclasses import dataclass

import pytest

from pipeline import judge
from pipeline.llm import CallMetrics, DiskCache, ProviderSpec
from pipeline.schemas import Transcript, TranscriptSegment

T = Transcript("call_j", "asr", [TranscriptSegment("S0001", "unknown", "Grüezi, Bank Lindenhof.", 0.0, 1.0),
                                  TranscriptSegment("S0002", "unknown", "Mein Passwort ist Sonnenblume.", 1.0, 3.0)],
               asr_model="m@1", duration_s=3.0)


@dataclass
class Fake:
    reply: str
    model: str = "fake"
    model_revision: str = "r1"
    spec: ProviderSpec = ProviderSpec(name="fake", base_url="http://127.0.0.1:1/v1", self_hosted=True)

    def __post_init__(self):
        self.calls = []

    def chat_with_metrics(self, messages, **kw):
        self.calls.append((messages, kw))
        return self.reply, CallMetrics("fake", "fake", True, None, 1.0, 10, 5, None, None, False, 1)


def answer(decision="alarm", cites=(("S0002", "Mein Passwort ist Sonnenblume"),)):
    return json.dumps({"decision": decision, "criterion": "credential_sharing", "risk": 0.9, "reason": "r",
                       "evidence": [{"segment_id": s, "speaker": "customer", "quote": q} for s, q in cites]})


def test_validated_citations_cached_and_asr_prompt(tmp_path):
    c = Fake(answer())
    r = judge.judge_call(T, client=c, cache=DiskCache(tmp_path))
    assert r.decision == "alarm" and len(r.valid_citations) == 1 and not r.cached
    msgs, kw = c.calls[0]
    assert "(speaker) Mein Passwort" in msgs[1]["content"] and "(unknown)" not in msgs[1]["content"]
    assert kw["temperature"] == 0.0 and kw["json_schema"] == judge.RESPONSE_SCHEMA
    assert judge.judge_call(T, client=c, cache=DiskCache(tmp_path)).cached and len(c.calls) == 1


def test_invented_citation_is_not_valid(tmp_path):
    r = judge.judge_call(T, client=Fake(answer(cites=(("S0002", "ich gebe Ihnen gern meine Kreditkarte"), ("S0099", "x")))),
                         cache=DiskCache(tmp_path))
    assert r.citations and r.valid_citations == []


def test_unusable_answer_raises_and_is_not_cached(tmp_path):
    with pytest.raises(judge.JudgeError):
        judge.judge_call(T, client=Fake("no json here"), cache=DiskCache(tmp_path))
    assert not list(tmp_path.rglob("*.json"))
