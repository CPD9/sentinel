"""Step 7: confidence components and formula (synthetic)."""
import copy
import json
from pathlib import Path

import pytest

from pipeline.confidence import ConfigError, compute, parse_confidence
from pipeline.schemas import AnalysisArtifact, Fact, Transcript, TranscriptSegment

RAW = json.loads((Path(__file__).parents[1] / "config" / "thresholds.json").read_text())["confidence"]
CP = parse_confidence(RAW)


def tr(lp=-0.2, nsp=0.0, reference=False):
    seg = TranscriptSegment("s1", "advisor", "x", None if reference else 0.0, None if reference else 1.0,
                            None if reference else lp, None if reference else nsp)
    return Transcript("c", "reference" if reference else "asr", [seg])


def analysis(score):
    ax = {"x": {"label": "time", "unit": "s"}, "value": {"label": "q", "unit": "score 0-1"}}
    return AnalysisArtifact.from_dict({"call_id": "c", "duration_s": 10.0, "sample_rate": 16000,
                                       "audio_quality": {"call_snr_db": 20.0, "call_score": score, "segments": [], "axes": ax}})


def run(t=None, facts=(), an=None, risk=0.0, conflicts=0, cp=CP):
    return compute(t or tr(), list(facts), an, risk, conflicts, 0.7, 0.4, 0.5, cp)


def test_missing_analysis_is_neutral_and_present_one_is_used():
    assert run().components["audio_quality"] == 1.0
    assert run(an=analysis(0.3)).components["audio_quality"] == 0.3
    assert run(an=analysis(0.3)).value < run().value


def test_reference_transcript_has_no_asr_concern():
    assert run(tr(reference=True)).components["asr"] == 1.0


def test_low_logprob_and_no_speech_lower_asr():
    assert run(tr(lp=-1.4, nsp=0.5)).components["asr"] < run(tr(lp=-0.6)).components["asr"] < 1.0


def test_threshold_proximity():
    assert run(risk=0.7).components["threshold_proximity"] == 0.0
    assert run(risk=0.4).components["threshold_proximity"] == 0.0
    assert run(risk=0.0).components["threshold_proximity"] == 1.0


def test_conflicts_and_dropped_facts_lower_confidence():
    dropped = Fact("F1", "advisor", "other", "other", ["s1"], "q", valid=False, drop_reason="x")
    assert run(conflicts=1).components["conflicts"] == 0.5
    assert run(facts=[dropped]).components["missing_evidence"] == 0.75


def test_formulas_differ_and_geometric_is_harsher():
    geo = parse_confidence({**RAW, "formula": "weighted_geometric"})
    kw = dict(t=tr(lp=-1.4, nsp=0.5), an=analysis(0.1))
    assert run(cp=geo, **kw).value < run(**kw).value
    assert 0.0 <= run(cp=geo, **kw).value <= 1.0


def test_breakdown_keys_are_the_schema_components():
    from pipeline.schemas import CONFIDENCE_COMPONENTS
    assert tuple(run().components) == CONFIDENCE_COMPONENTS


def test_bad_params_rejected():
    bad = copy.deepcopy(RAW)
    bad["formula"], bad["gate_scope"] = "magic", "sometimes"
    bad["weights"]["asr"] = -1
    with pytest.raises(ConfigError) as e:
        parse_confidence(bad)
    assert len(e.value.errors) == 3
    worse = copy.deepcopy(RAW)
    worse["params"]["asr_logprob_floor"] = 0.0
    with pytest.raises(ConfigError, match="floor < asr_logprob_ceiling"):
        parse_confidence(worse)
