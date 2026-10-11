"""pipeline/judge_multi.py: one focused check per criterion, risk = max, top check's citations. Fake client."""
import json
from dataclasses import dataclass

from pipeline import judge_multi as jm
from pipeline.llm import CallMetrics, DiskCache, ProviderSpec
from pipeline.schemas import Transcript, TranscriptSegment

T = Transcript("call_m", "asr", [TranscriptSegment("S0001", "unknown", "Ich teile die Zahlung in zwei Teile auf.", 0.0, 2.0)],
               asr_model="m@1", duration_s=2.0)


@dataclass
class Fake:
    model: str = "fake"
    model_revision: str = "r1"
    spec: ProviderSpec = ProviderSpec(name="fake", base_url="http://127.0.0.1:1/v1", self_hosted=True)

    def __post_init__(self):
        self.prompts = []

    def chat_with_metrics(self, messages, **kw):
        self.prompts.append(messages[0]["content"])
        hit = "control_evasion:" in messages[0]["content"]
        ans = {"decision": "alarm" if hit else "no_alert", "risk": 0.9 if hit else 0.4, "reason": "r",
               "evidence": [{"segment_id": "S0001", "speaker": "customer", "quote": "Ich teile die Zahlung in zwei Teile auf"}] if hit else []}
        return json.dumps(ans), CallMetrics("fake", "fake", True, None, 1.0, 10, 5, None, None, False, 1)


def test_one_check_per_criterion_max_risk_and_top_citations(tmp_path):
    c = Fake()
    r = jm.judge_call_multi(T, client=c, cache=DiskCache(tmp_path))
    assert len(c.prompts) == len(jm.CHECKED) == 6 and all(p.count("You check exactly ONE criterion") == 1 for p in c.prompts)
    assert r.criterion == "control_evasion" and r.risk == 0.9 and r.decision == "alarm" and len(r.valid_citations) == 1
    assert all(ch.risk <= 0.1 for ch in r.checks if ch.criterion != "control_evasion")   # "not met" caps the risk
    jm.judge_call_multi(T, client=c, cache=DiskCache(tmp_path))
    assert len(c.prompts) == 6                                                           # second call fully cached


def test_definitions_are_shared_with_the_single_judge():
    from pipeline import judge
    for name, text in jm.DEFINITIONS.items():
        assert name in jm.CHECKED and text.split()[0] in judge.SYSTEM_PROMPT
