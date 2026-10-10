"""Fact extraction (step 4) with a fake client: no network, no GPU."""
import inspect
import json
from dataclasses import dataclass

import pytest

from pipeline import extract as ex
from pipeline import llm
from pipeline.decide import config_from_dicts, decide_call, load_config
from pipeline.llm import CallMetrics, DiskCache, ProviderSpec, extraction_cache_key
from pipeline.schemas import Fact, Transcript, TranscriptSegment

SEGS = [("T001", "advisor", "Grüezi, Bank Lindenhof."),
        ("T002", "customer", "Ich ha mis Passwort vergässe."),
        ("T003", "advisor", "Säged Sie nie öpperem Ihres Passwort."),
        ("T004", "customer", "Mis Passwort isch Sunneblueme."),
        ("T005", "advisor", "Merci, ich schicke en Link.")]


def tr(segs=SEGS):
    return Transcript("call_x", "reference", [TranscriptSegment(*s) for s in segs])


def raw_fact(**kw):
    base = dict(speaker="customer", act="disclose", info_type="credentials", recipient_third_party=False,
                secrecy_cue=False, counter_evidence=None, segment_ids=["T004"], quote="Mis Passwort isch Sunneblueme",
                gloss_de="Mein Passwort ist Sonnenblume")
    return {**base, **kw}


def reply(*facts):
    return json.dumps({"facts": list(facts)})


def metrics(**kw):
    base = dict(provider="fake", model="m", self_hosted=True, ttft_ms=None, wall_ms=10.0, input_tokens=100,
                output_tokens=20, tokens_per_s=None, cost_usd=None, streamed=False, attempts=1)
    return CallMetrics(**{**base, **kw})


@dataclass
class FakeClient:
    replies: list
    model: str = "fake-model"
    model_revision: str | None = "rev1"
    spec: ProviderSpec = ProviderSpec(name="fake", base_url="http://127.0.0.1:1/v1", self_hosted=True)

    def __post_init__(self):
        self.calls = []

    def probe(self):
        self.model_revision = "probed"

    def chat_with_metrics(self, messages, temperature=0.0, max_tokens=1024, json_schema=None, stream=True):
        self.calls.append({"messages": messages, "temperature": temperature, "json_schema": json_schema,
                           "max_tokens": max_tokens})
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return r, metrics()


def run(client, transcript=None, tmp=None, **kw):
    return ex.extract_facts(transcript or tr(), client=client, cache=DiskCache(tmp), **kw)


def test_valid_reply(tmp_path):
    (f,) = run(FakeClient([reply(raw_fact())]), tmp=tmp_path)
    assert f.valid and f.fact_id == "f001" and f.segment_ids == ["T004"] and f.gloss_de.startswith("Mein")


def test_request_uses_temperature_zero_and_schema(tmp_path):
    c = FakeClient([reply()])
    assert run(c, tmp=tmp_path) == []
    assert c.calls[0]["temperature"] == 0.0 and c.calls[0]["json_schema"] == ex.prompt.FACT_SCHEMA


def test_prompt_lists_segments_and_leaks_nothing(tmp_path):
    c = FakeClient([reply()])
    run(c, tmp=tmp_path)
    text = "\n".join(m["content"] for m in c.calls[0]["messages"])
    assert "[T004] (customer) Mis Passwort isch Sunneblueme." in text
    assert "call_x" not in text and "Stufe" not in text and "keyword" not in text.lower()


def test_fenced_and_prose_wrapped_json(tmp_path):
    out = run(FakeClient(["Hier:\n```json\n" + reply(raw_fact()) + "\n```\nFertig."]), tmp=tmp_path)
    assert len(out) == 1 and out[0].valid


def test_think_block_is_stripped(tmp_path):
    out = run(FakeClient(["<think>Ich muss {\"facts\": []} ausgeben</think>\n" + reply(raw_fact())]), tmp=tmp_path)
    assert len(out) == 1 and out[0].valid
    assert ex.clean_reply("<think>x</think>  {\"facts\": []}") == '{"facts": []}'
    assert ex.clean_reply('ok <think>never ends {"facts": []}') == "ok"


def test_malformed_then_repair_succeeds(tmp_path):
    rep = []
    c = FakeClient(["{facts: oops", reply(raw_fact())])
    out = run(c, tmp=tmp_path, report=rep)
    assert len(c.calls) == 2 and out[0].valid and rep[0]["repaired"] and len(rep[0]["metrics"]) == 2
    assert "not usable" in c.calls[1]["messages"][-1]["content"]


def test_malformed_twice_raises(tmp_path):
    c = FakeClient(["nonsense", "still nonsense"])
    with pytest.raises(ex.ExtractionError):
        run(c, tmp=tmp_path)
    assert len(c.calls) == 2
    assert not list(tmp_path.rglob("*.json"))      # failures are never cached


def test_wrong_top_level_shape_is_repaired(tmp_path):
    c = FakeClient([json.dumps([raw_fact()]), reply(raw_fact())])
    assert run(c, tmp=tmp_path)[0].valid and len(c.calls) == 2


def test_hallucinated_segment_id_is_dropped_with_reason(tmp_path):
    (f,) = run(FakeClient([reply(raw_fact(segment_ids=["T042"]))]), tmp=tmp_path)
    assert not f.valid and "unknown segment id" in f.drop_reason


def test_case_insensitive_id_is_resolved(tmp_path):
    (f,) = run(FakeClient([reply(raw_fact(segment_ids=["t004"]))]), tmp=tmp_path)
    assert f.valid and f.segment_ids == ["T004"]


def test_wrong_quote_wrong_speaker_and_empty_quote(tmp_path):
    out = run(FakeClient([reply(raw_fact(quote="Ich überwiise hunderttuusig Franke uf Zypere"),
                                raw_fact(segment_ids=["T002"], quote="Ich ha mis Passwort vergässe", speaker="advisor"),
                                raw_fact(segment_ids=["T005"], speaker="advisor", quote=""))]), tmp=tmp_path)
    assert [f.valid for f in out] == [False, False, False]
    reasons = {f.drop_reason for f in out}
    assert any(r.startswith("quote not in") for r in reasons) and any(r.startswith("speaker") for r in reasons)
    assert "empty quote" in reasons


def test_invalid_enum_is_kept_invalid_and_coerced(tmp_path):
    (f,) = run(FakeClient([reply(raw_fact(act="steal"))]), tmp=tmp_path)
    assert not f.valid and f.act == "other" and f.drop_reason.startswith("invalid field")


def test_no_citation_keeps_a_trace_valid_fact(tmp_path):
    (f,) = run(FakeClient([reply(raw_fact(segment_ids=[]))]), tmp=tmp_path)
    assert not f.valid and f.segment_ids and f.drop_reason == "no segment ids cited"


def many(n=40, text="Das isch en längere Satz mit viel Inhalt über d Kontoüberwiisig vo geschter."):
    return tr([(f"T{i:03d}", "advisor" if i % 2 else "customer", text) for i in range(1, n + 1)])


def test_windows_cover_everything_overlap_and_respect_budget():
    t = many(200)
    ws = ex.make_windows(t.segments)
    assert len(ws) > 1
    assert {s.id for w in ws for s in w} == {s.id for s in t.segments}
    for a, b in zip(ws, ws[1:]):
        assert len({s.id for s in a} & {s.id for s in b}) >= 1
    assert all(sum(ex._cost(s) for s in w) <= ex.WINDOW_TOKENS for w in ws)
    # leaves room in the 8192 context for the prompt and the answer
    assert ex.WINDOW_TOKENS + 900 + ex.MAX_OUTPUT_TOKENS < ex.CONTEXT_TOKENS - 1500


def test_short_call_is_one_window_and_single_oversized_segment_stands_alone():
    assert len(ex.make_windows(tr().segments)) == 1
    big = tr([("T001", "advisor", "x " * 20000), ("T002", "customer", "kurz")])
    assert [len(w) for w in ex.make_windows(big.segments)] == [1, 1]


def test_duplicate_across_windows_is_merged(tmp_path):
    t = many(200)
    ws = ex.make_windows(t.segments)
    shared = [s.id for s in ws[0] if s.id in {x.id for x in ws[1]}][0]
    seg = next(s for s in t.segments if s.id == shared)
    f_a = raw_fact(speaker=seg.speaker, segment_ids=[shared], quote=seg.text[:30])
    f_b = raw_fact(speaker=seg.speaker, segment_ids=[shared, ws[1][-1].id], quote=seg.text)
    c = FakeClient([reply(f_a)] + [reply(f_b)] + [reply()] * 10)
    out = run(c, t, tmp=tmp_path)
    assert len(out) == 1 and shared in out[0].segment_ids and out[0].quote == seg.text
    assert out[0].fact_id == "f001"


def test_cache_hit_avoids_second_call(tmp_path):
    c = FakeClient([reply(raw_fact())])
    first = run(c, tmp=tmp_path)
    rep = []
    second = run(c, tmp=tmp_path, report=rep)
    assert len(c.calls) == 1 and first == second and rep[0]["cached"]


def test_cache_key_ignores_keywords_but_not_content_model_provider_prompt():
    segs = [{"id": s.id, "speaker": s.speaker, "text": s.text} for s in tr().segments]
    k = lambda segs=segs, m="m", r="r", p=ex.PROMPT_VERSION_FULL, prov="fake": extraction_cache_key(segs, m, r, p, provider=prov)
    base = k()
    assert k() == base
    assert k(segs=segs[:-1]) != base and k(m="n") != base and k(r="s") != base and k(p="x") != base and k(prov="o") != base
    other = [dict(segs[0], text="anders")] + segs[1:]
    assert k(segs=other) != base


def test_keyword_edit_does_not_invalidate_the_cache(tmp_path):
    c = FakeClient([reply(raw_fact())])
    run(c, tmp=tmp_path)
    kwd = json.loads((llm.REPO_ROOT / "config" / "keywords.json").read_text(encoding="utf-8"))
    next(iter(kwd["families"].values()))["terms"].append("völlig neues stichwort")
    rules, thresholds = _rules_thresholds()
    config_from_dicts(kwd, rules, thresholds)
    run(c, tmp=tmp_path)
    assert len(c.calls) == 1


def _rules_thresholds():
    import yaml
    d = llm.REPO_ROOT / "config"
    return (yaml.safe_load((d / "rules.yaml").read_text(encoding="utf-8")),
            json.loads((d / "thresholds.json").read_text(encoding="utf-8")))


def test_contract_signature_matches_m6():
    sig = inspect.signature(ex.extract_facts)
    params = list(sig.parameters.values())
    assert params[0].name == "transcript" and params[0].kind is params[0].POSITIONAL_OR_KEYWORD
    assert all(p.kind is p.KEYWORD_ONLY and p.default is not p.empty for p in params[1:])
    assert sig.return_annotation in (list[Fact], "list[Fact]")


def test_versions_are_published_after_a_run(tmp_path):
    run(FakeClient([reply()]), tmp=tmp_path)
    assert ex.VERSIONS["llm"] == "fake-model@rev1" and ex.VERSIONS["prompt"] == ex.PROMPT_VERSION_FULL
    assert ex.VERSIONS["provider"] == "fake" and ex.VERSIONS["self_hosted"] is True


def test_missing_revision_triggers_probe(tmp_path):
    c = FakeClient([reply()], model_revision=None)
    run(c, tmp=tmp_path)
    assert c.model_revision == "probed"


def test_llm_failure_propagates(tmp_path):
    class Dead(FakeClient):
        def chat_with_metrics(self, *a, **k):
            raise llm.LLMError("cannot reach")
    with pytest.raises(llm.LLMError):
        run(Dead([reply()]), tmp=tmp_path)


def test_dropped_high_risk_fact_never_alarms(tmp_path):
    """End to end with the real rules: a hallucinated credential disclosure -> review, not alarm."""
    t = tr()
    cfg = load_config()
    good = run(FakeClient([reply(raw_fact())]), t, tmp=tmp_path / "a")
    assert decide_call(t, good, None, cfg).decision in ("alarm", "review")
    bad = run(FakeClient([reply(raw_fact(segment_ids=["T042"]))]), t, tmp=tmp_path / "b")
    trace = decide_call(t, bad, None, cfg)
    assert trace.decision == "review" and trace.decision_path == "missing_evidence"
