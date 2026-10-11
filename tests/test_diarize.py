import json
import sys
from pathlib import Path

import pytest

from pipeline import diarize
from pipeline.llm import DiskCache
from pipeline.schemas import SchemaError, SpeakerRoles

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_speakers  # noqa: E402

SEGS = [{"id": "S1", "start_s": 0.0, "end_s": 2.0, "text": "Grüezi, Rosenau Bank, Meier."},
        {"id": "S2", "start_s": 2.0, "end_s": 4.0, "text": "Ich möchte Aktien kaufen."},
        {"id": "S3", "start_s": 4.0, "end_s": 6.0, "text": "Gerne. Ja genau."},
        {"id": "S4", "start_s": 9.0, "end_s": 10.0, "text": "silence"}]
TURNS = [{"start_s": 0.0, "end_s": 2.1, "cluster": "SPEAKER_01"},
         {"start_s": 2.1, "end_s": 4.0, "cluster": "SPEAKER_00"},
         {"start_s": 4.0, "end_s": 5.0, "cluster": "SPEAKER_01"},
         {"start_s": 5.0, "end_s": 6.0, "cluster": "SPEAKER_00"}]


def test_join_turns_largest_overlap_and_mixed():
    j = {x["id"]: x for x in diarize.join_turns(SEGS, TURNS)}
    assert j["S1"]["cluster"] == "SPEAKER_01" and not j["S1"]["mixed"]
    assert j["S2"]["cluster"] == "SPEAKER_00" and j["S2"]["overlap_frac"] == 0.95
    assert j["S3"]["mixed"] is True                      # 50/50 split between the two voices
    assert j["S4"]["cluster"] is None and j["S4"]["overlap_frac"] == 0.0


class StubClient:
    model, model_revision = "stub", "r1"

    class spec:
        name = "stub"

    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def chat_with_metrics(self, messages, temperature=0.0, max_tokens=0, json_schema=None):
        self.calls += 1

        class M:
            @staticmethod
            def to_dict():
                return {}
        return json.dumps(self.answers.pop(0)), M()


def test_map_clusters_and_cache(tmp_path):
    joined = diarize.join_turns(SEGS, TURNS)
    client = StubClient([{"rationale": "greets with bank name", "advisor_cluster": "SPEAKER_01"}])
    cache = DiskCache(tmp_path)
    roles, why = diarize.map_clusters(SEGS, joined, client=client, cache=cache)
    assert roles == {"SPEAKER_01": "advisor", "SPEAKER_00": "customer"} and why
    assert diarize.map_clusters(SEGS, joined, client=client, cache=cache)[0] == roles   # second call from cache
    assert client.calls == 1


def test_content_only_windows_cover_every_segment(tmp_path, monkeypatch):
    monkeypatch.setattr(diarize, "WINDOW", 3)
    monkeypatch.setattr(diarize, "OVERLAP", 1)
    client = StubClient([{"roles": [{"id": "S1", "role": "advisor"}, {"id": "S2", "role": "customer"},
                                    {"id": "S3", "role": "unknown"}]},
                         {"roles": [{"id": "S3", "role": "advisor"}, {"id": "S4", "role": "customer"}]}])
    out = diarize.label_segments_content_only(SEGS, client=client, cache=DiskCache(tmp_path))
    assert out == {"S1": "advisor", "S2": "customer", "S3": "advisor", "S4": "customer"}


def test_schema_rejects_bad_role():
    d = {"call_id": "call_001", "label_source": "content only", "mapper": {}, "transcript": {},
         "segments": [{"id": "S1", "role": "boss"}]}
    with pytest.raises(SchemaError):
        SpeakerRoles.from_dict(d)
    d["segments"][0]["role"] = "advisor"
    assert SpeakerRoles.from_dict(d).segments[0].role == "advisor"


def test_eval_alignment_scores_matched_words():
    asr = [{"id": "S1", "text": "Grüezi Rosenau Bank"}, {"id": "S2", "text": "ich möchte kaufen"}]
    pred = {"label_source": "content only", "segments": [{"id": "S1", "role": "advisor"}, {"id": "S2", "role": "advisor"}]}
    ref = [{"speaker": "advisor", "text": "Grüezi, Rosenau Bank, Meier."},
           {"speaker": "customer", "text": "Ich möchte gern kaufen."}]
    r = eval_speakers.score_call(asr, pred, ref)
    assert r["words"] == 6 and r["matched"] == 6 and r["correct"] == 3
