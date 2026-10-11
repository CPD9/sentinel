"""Steps 3 + 6-8 behind one entry point: `decide_call(transcript, facts, analysis, config) -> DecisionTrace`.

Pure and CPU-only: keywords -> rules -> confidence -> decision, no LLM, no I/O. When thresholds, rules or keywords
change, call it again with the cached transcript and cached facts.

Priority order (CLAUDE.md), first match wins; `decision_path` records the step:
  1. review  stage_error             a stage failed (stage_errors given, or facts is None)
  2. review  missing_evidence        a dropped fact would have given a rule (with no valid supporting fact) a risk >= the
                                     review threshold AND above every supported rule's risk, i.e. it could have changed
                                     the outcome; or a rule reaches the alarm threshold on keywords alone. A dropped
                                     fact that could not change the outcome only lowers the confidence component.
  3. review  contradictory_evidence  a supporting and a counter fact cite the same segment
  4. review  low_confidence          confidence < gate (scope per thresholds.json: "any" | "risky_only")
  5. alarm        a fired rule with valid supporting facts and risk >= alarm threshold
  6. review       review_band: risk in [review, alarm)
  7. no_alert     otherwise
Structural guarantee: no valid supporting fact -> never an alarm, whatever the thresholds.
`why_not_flagged` / `what_would_change` stay None: the narrative runs after the decision is locked.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path

from pipeline import confidence as conf
from pipeline import keywords as kw
from pipeline import rules as rl
from pipeline.keywords import ConfigError
from pipeline.schemas import (AnalysisArtifact, DecisionTrace, Fact, KeywordHit, SchemaError, StageError, Thresholds, Transcript,
                              Versions)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@dataclass
class Config:
    keywords: kw.KeywordConfig
    rules: rl.RulesConfig
    thresholds: Thresholds
    confidence: conf.ConfidenceParams
    rules_version: str
    decision_source: str = "rules"              # "direct_judge": thresholds apply to the cached S4 judge risk
    keyword_review: bool = False                # judge mode: keyword hits alone may raise a call to review
    keyword_review_min_segments: int = 2        # ... when one family has hits in at least this many segments


def config_from_dicts(keywords: dict, rules: dict, thresholds: dict) -> Config:
    t = {k: thresholds.get(k) for k in ("alarm", "review", "confidence_gate")}
    errs = [f"thresholds.{k} must be a number in [0, 1]" for k, v in t.items()
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1]
    if not errs and not t["review"] < t["alarm"]:
        errs.append("thresholds: need review < alarm")
    if errs:
        raise ConfigError(errs)
    src = thresholds.get("decision_source", "rules")
    if src not in ("rules", "direct_judge"):
        errs.append(f"thresholds.decision_source {src!r}: use 'rules' or 'direct_judge'")
    kr = thresholds.get("keyword_review") or {}
    if not isinstance(kr, dict) or not isinstance(kr.get("enabled", False), bool) \
            or not (isinstance(kr.get("min_segments", 2), int) and kr.get("min_segments", 2) >= 1):
        errs.append("thresholds.keyword_review: {enabled: bool, min_segments: int >= 1}")
        kr = {}
    if errs:
        raise ConfigError(errs)
    digest = hashlib.sha256(json.dumps([rules, keywords, thresholds], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
    rc = rl.parse_rules(rules)
    return Config(kw.parse_keywords(keywords), rc, Thresholds(float(t["alarm"]), float(t["review"]), float(t["confidence_gate"])),
                  conf.parse_confidence(thresholds.get("confidence") or {}), f"{rc.version}+{digest}",
                  src, bool(kr.get("enabled", False)), int(kr.get("min_segments", 2)))


def judge_decide(trace: DecisionTrace, judge: dict, config: Config) -> DecisionTrace:
    """decision_source "direct_judge": decide from the cached S4 judge result (pipeline/judge.py, JudgeResult.to_dict())
    with the adjustable thresholds. Pure, CPU only: the what-if simulator re-decides 62 calls in milliseconds.
      alarm   judge risk >= alarm AND >= 1 validated citation AND confidence >= gate
      review  judge risk >= review (an alarm-level risk without a validated citation or confidence lands here)
      review  keyword_review on and one keyword family hit in >= min_segments segments (never an alarm)
      no_alert otherwise
    A call whose stages failed stays as decide_call left it (review). Facts and rules stay in the trace as the why."""
    if trace.decision_path == "stage_error":
        return trace
    th = trace.thresholds
    risk = float(judge.get("risk") or 0.0)
    cited = any(c.get("valid") for c in judge.get("citations") or [])
    conf_ok = trace.confidence is not None and trace.confidence >= th.confidence_gate
    segs: dict[str, set] = {}
    for h in trace.keyword_hits:
        segs.setdefault(h.family, set()).add(h.segment_id)
    if risk >= th.alarm and cited and conf_ok:
        path = "judge_alarm"
    elif risk >= th.review:
        path = "judge_review"
    elif config.keyword_review and max((len(v) for v in segs.values()), default=0) >= config.keyword_review_min_segments:
        path = "keyword_review"
    else:
        path = "judge_no_alert"
    trace.decision_path, trace.decision, trace.risk_score = path, ("alarm" if path == "judge_alarm" else
                                                                   "no_alert" if path == "judge_no_alert" else "review"), risk
    return trace


def load_config(config_dir: Path = CONFIG_DIR) -> Config:
    import yaml
    d = Path(config_dir)
    return config_from_dicts(json.loads((d / "keywords.json").read_text(encoding="utf-8")),
                             yaml.safe_load((d / "rules.yaml").read_text(encoding="utf-8")) or {},
                             json.loads((d / "thresholds.json").read_text(encoding="utf-8")))


def with_thresholds(config: Config, **kw_: float) -> Config:
    """Copy of `config` with some of alarm / review / confidence_gate replaced (used by what-if previews and tests)."""
    return replace(config, thresholds=replace(config.thresholds, **kw_))


def _reconcile(facts: list[Fact], transcript: Transcript) -> list[Fact]:
    """A 'valid' fact citing a segment the transcript does not have counts as dropped."""
    ids = {s.id for s in transcript.segments}
    out = []
    for f in facts:
        bad = [s for s in f.segment_ids if s not in ids]
        if f.valid and bad:
            f = replace(f, valid=False, drop_reason=f"cited segment(s) not in transcript: {', '.join(bad)}")
        out.append(f)
    return out


def decide_call(transcript: Transcript, facts: list[Fact] | None, analysis: AnalysisArtifact | None, config: Config,
                stage_errors: list[StageError] | None = None, versions: Versions | None = None,
                *, hits: list[KeywordHit] | None = None, validate: bool = True) -> DecisionTrace:
    """`hits`: optional precomputed `keywords.find_hits(transcript, config.keywords)` (what-if search reuses them).
    `validate=False` skips the schema self-check of the returned trace (only the suggestion search does, and it re-checks its results)."""
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    stage_failed = bool(stage_errors) or facts is None
    facts = _reconcile(facts or [], transcript)
    th = config.thresholds

    if hits is None:
        hits = kw.find_hits(transcript, config.keywords)
    timings["keywords"] = time.perf_counter() - t0
    t1 = time.perf_counter()
    ra = rl.evaluate(facts, hits, transcript, config.rules)
    risk = round(ra.max_risk, 4)
    timings["rules"] = time.perf_counter() - t1
    t2 = time.perf_counter()
    cb = conf.compute(transcript, facts, analysis, risk, len(ra.conflicts), th.alarm, th.review, th.confidence_gate,
                      config.confidence)
    timings["confidence"] = time.perf_counter() - t2

    t3 = time.perf_counter()
    unsupported_high = any(not ra.supported[r.criterion] and r.risk >= th.alarm for r in ra.results)
    supported_max = max((r.risk for r in ra.results if ra.supported[r.criterion]), default=0.0)
    could_matter = any(p >= th.review and p > supported_max for _, _, p in ra.unsupported_dropped)
    risky = risk >= th.review or bool(hits)
    low_conf = cb.value < th.confidence_gate and (config.confidence.gate_scope == "any" or risky)
    if stage_failed:
        path = "stage_error"
    elif could_matter or unsupported_high:
        path = "missing_evidence"
    elif ra.conflicts:
        path = "contradictory_evidence"
    elif low_conf:
        path = "low_confidence"
    elif any(r.fired and ra.supported[r.criterion] and r.risk >= th.alarm for r in ra.results):
        path = "alarm"
    elif risk >= th.review:
        path = "review_band"
    else:
        path = "no_alert"
    decision = {"alarm": "alarm", "no_alert": "no_alert"}.get(path, "review")
    timings["decide"] = time.perf_counter() - t3

    v = Versions(**{**(versions.__dict__ if versions else {}), "rules": config.rules_version})
    trace = DecisionTrace(call_id=transcript.call_id, decision=decision, decision_path=path, risk_score=risk,
                          confidence=cb.value, thresholds=th, facts=facts, keyword_hits=hits, rules=ra.results,
                          confidence_breakdown=cb, timings_s={k: round(x, 6) for k, x in timings.items()}, versions=v,
                          is_mock=transcript.is_mock)
    errs = DecisionTrace.validate(trace.to_dict()) if validate else []
    if errs:
        raise SchemaError(errs)
    return trace
