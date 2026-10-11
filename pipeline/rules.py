"""Step 6: one rule per criterion in schemas.CRITERIA, as data (config/rules.yaml) over validated facts + keyword hits.

A rule returns a `RuleResult` {criterion, risk 0-1, fired, reason, fact_ids + keyword_hit_ids (the inputs)}.

  supporting fact   a valid fact matching one `when` condition (act, info_type, recipient_third_party, secrecy_cue,
                    speaker); risk = best matching condition (+ keyword_boost if a family hit lies in its cited segments).
                    `needs_keyword` rules count a fact only with such a hit.
  counter-evidence  valid facts in the rule's scope with act warn / refuse / hypothetical / quote that are AT OR AFTER the
                    supporting fact in transcript order and share no segment with it, plus the fact's own non-empty
                    `counter_evidence` text. risk *= prod(1 - discount). A warning BEFORE a disclosure does not excuse it,
                    except for speakers in defaults.prior_counter_speakers (e.g. a customer who discloses after the
                    advisor warned them: the advisor acted correctly).
  rule risk         max over supporting facts, floored by `keyword_only_risk` when the family has hits; capped by max_risk.
  fired             has a supporting fact and risk >= fire_at.
  conflict          a supporting and a counter fact that cite the SAME segment (one utterance read both ways).
                    Request-then-refusal on different segments is counter-evidence, not a conflict.

Placeholders: every number in rules.yaml is a judgement value, not tuned on data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline.keywords import ConfigError
from pipeline.schemas import (CRITERIA, CRITERION_BY_FAMILY, FACT_ACTS, INFO_TYPES, SPEAKERS, Fact, KeywordHit,
                              RuleResult, Transcript)

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = REPO_ROOT / "config" / "rules.yaml"
COUNTER_ACTS = ("warn", "refuse", "hypothetical", "quote")
_FAMILY_OF = {c: f for f, c in CRITERION_BY_FAMILY.items()}
_WHEN_KEYS = ("act", "info_type", "recipient_third_party", "secrecy_cue", "speaker")


@dataclass
class Condition:
    when: dict
    risk: float


@dataclass
class RuleCfg:
    criterion: str
    enabled: bool
    info_types: list[str] | None
    conditions: list[Condition]
    needs_keyword: bool = False
    keyword_only_risk: float | None = None
    max_risk: float = 1.0


@dataclass
class RulesConfig:
    version: str
    fire_at: float
    keyword_boost: float
    keyword_only_risk: float
    counter_discount: dict[str, float]
    rules: dict[str, RuleCfg]
    prior_counter_speakers: tuple[str, ...] = ()   # their facts are also discounted by EARLIER counters of the other side


def parse_rules(d: dict) -> RulesConfig:
    errs: list[str] = []

    def unit(v, where):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
            errs.append(f"{where} must be a number in [0, 1]")
            return 0.0
        return float(v)

    df = d.get("defaults") or {}
    fire_at, boost = unit(df.get("fire_at", 0.5), "defaults.fire_at"), unit(df.get("keyword_boost", 0.05), "defaults.keyword_boost")
    kw_only = unit(df.get("keyword_only_risk", 0.15), "defaults.keyword_only_risk")
    disc = {}
    for k, v in (df.get("counter_discount") or {}).items():
        if k not in (*COUNTER_ACTS, "self"):
            errs.append(f"defaults.counter_discount.{k}: unknown (use {COUNTER_ACTS} or self)")
        disc[k] = unit(v, f"defaults.counter_discount.{k}")
    for k in (*COUNTER_ACTS, "self"):
        disc.setdefault(k, 0.0)
    prior = tuple(df.get("prior_counter_speakers") or ())
    errs += [f"defaults.prior_counter_speakers: unknown speaker {x!r}" for x in prior if x not in SPEAKERS]
    rules: dict[str, RuleCfg] = {}
    for i, r in enumerate(d.get("rules") or []):
        w = f"rules[{i}]"
        crit = r.get("criterion")
        if crit not in CRITERIA:
            errs.append(f"{w}.criterion {crit!r} not in {CRITERIA}")
            continue
        if crit in rules:
            errs.append(f"{w}: duplicate rule for {crit}")
        its = (r.get("scope") or {}).get("info_types")
        if its is not None and (not isinstance(its, list) or any(x not in INFO_TYPES for x in its)):
            errs.append(f"{w}.scope.info_types must be null or a list from {INFO_TYPES}")
            its = None
        conds = []
        for j, c in enumerate(r.get("facts") or []):
            when = c.get("when") or {}
            for k, v in when.items():
                if k not in _WHEN_KEYS:
                    errs.append(f"{w}.facts[{j}].when.{k}: unknown key (use {_WHEN_KEYS})")
                elif k == "act" and v not in FACT_ACTS:
                    errs.append(f"{w}.facts[{j}].when.act {v!r} not in {FACT_ACTS}")
                elif k == "info_type" and v not in INFO_TYPES:
                    errs.append(f"{w}.facts[{j}].when.info_type {v!r} not in {INFO_TYPES}")
                elif k == "speaker" and v not in SPEAKERS:
                    errs.append(f"{w}.facts[{j}].when.speaker {v!r} not in {SPEAKERS}")
                elif k in ("recipient_third_party", "secrecy_cue") and not isinstance(v, bool):
                    errs.append(f"{w}.facts[{j}].when.{k} must be true/false")
            conds.append(Condition(dict(when), unit(c.get("risk"), f"{w}.facts[{j}].risk")))
        rules[crit] = RuleCfg(crit, bool(r.get("enabled", True)), its, conds, bool(r.get("needs_keyword", False)),
                              None if r.get("keyword_only_risk") is None else unit(r["keyword_only_risk"], f"{w}.keyword_only_risk"),
                              unit(r.get("max_risk", 1.0), f"{w}.max_risk"))
    errs += [f"rules: missing a rule for criterion {c}" for c in CRITERIA if c not in rules]
    if errs:
        raise ConfigError(errs)
    return RulesConfig(str(d.get("version", "rules")), fire_at, boost, kw_only, disc, rules, prior)


def load_rules(path: Path = RULES_FILE) -> RulesConfig:
    return parse_rules(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


@dataclass
class RuleAnalysis:
    results: list[RuleResult]
    supported: dict[str, bool]                                   # criterion -> has a valid supporting fact
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)       # (criterion, supporting id, counter id)
    unsupported_dropped: list[tuple[str, str, float]] = field(default_factory=list)  # (criterion, dropped fact id, risk it would have had)

    @property
    def max_risk(self) -> float:
        return max((r.risk for r in self.results), default=0.0)


def _in_scope(rule: RuleCfg, f: Fact) -> bool:
    return rule.info_types is None or f.info_type in rule.info_types


def _matches(when: dict, f: Fact) -> bool:
    return all(getattr(f, k) == v for k, v in when.items())


def evaluate(facts: list[Fact], hits: list[KeywordHit], transcript: Transcript, cfg: RulesConfig) -> RuleAnalysis:
    pos = {s.id: i for i, s in enumerate(transcript.segments)}
    at = lambda f: min((pos.get(s, len(pos)) for s in f.segment_ids), default=len(pos))
    valid = [f for f in facts if f.valid]
    dropped = [f for f in facts if not f.valid]
    results, supported, conflicts, unsupported = [], {}, [], []
    for crit, rule in cfg.rules.items():
        if not rule.enabled:
            continue
        fam_hits = [h for h in hits if h.family == _FAMILY_OF.get(crit)]
        hit_ids = [h.hit_id for h in fam_hits]
        hit_segs = {h.segment_id for h in fam_hits}

        def base(f: Fact) -> float | None:
            if rule.needs_keyword and not hit_segs & set(f.segment_ids):
                return None
            best = [c.risk for c in rule.conditions if _matches(c.when, f)]
            return max(best) if best else None

        counters = [f for f in valid if f.act in COUNTER_ACTS and _in_scope(rule, f)]
        sup: list[tuple[Fact, float, list[Fact]]] = []
        for f in valid:
            b = base(f)
            if b is None:
                continue
            if hit_segs & set(f.segment_ids):
                b += cfg.keyword_boost
            applied = [c for c in counters if not set(c.segment_ids) & set(f.segment_ids)
                       and (at(c) >= at(f) or (f.speaker in cfg.prior_counter_speakers and c.speaker != f.speaker))]
            keep = 1.0
            for c in applied:
                keep *= 1.0 - cfg.counter_discount[c.act]
            if f.counter_evidence:
                keep *= 1.0 - cfg.counter_discount["self"]
            sup.append((f, min(1.0, b) * keep, applied))
            conflicts += [(crit, f.fact_id, c.fact_id) for c in counters if set(c.segment_ids) & set(f.segment_ids)]
        supported[crit] = bool(sup)
        if not sup:
            unsupported += [(crit, f.fact_id, base(f)) for f in dropped if base(f) is not None]
        kw_only = (rule.keyword_only_risk if rule.keyword_only_risk is not None else cfg.keyword_only_risk) if hit_ids else 0.0
        risk = min(rule.max_risk, max([r for _, r, _ in sup] + [kw_only]))
        fired = bool(sup) and risk >= cfg.fire_at
        fact_ids = list(dict.fromkeys([f.fact_id for f, _, _ in sup] + [c.fact_id for _, _, ap in sup for c in ap]
                                      + [c.fact_id for c in counters if not sup]))
        if sup:
            top, top_risk, top_counters = max(sup, key=lambda x: x[1])
            reason = f"{crit}: {top.speaker} {top.act} of {top.info_type} ({top.fact_id}), risk {top_risk:.2f}"
            if top_counters or top.counter_evidence:
                reason += " after counter-evidence " + ", ".join([c.fact_id for c in top_counters] + (["own note"] if top.counter_evidence else []))
            reason += "." if fired else f"; below fire level {cfg.fire_at:.2f}."
        elif hit_ids:
            reason = f"{crit}: {len(hit_ids)} keyword hit(s) in family {_FAMILY_OF.get(crit)} but no supporting fact."
        else:
            reason = f"{crit}: no supporting fact or keyword hit."
        results.append(RuleResult(crit, round(risk, 4), fired, reason, fact_ids, hit_ids))
    return RuleAnalysis(results, supported, conflicts, unsupported)
