"""What-if simulator: "if this config change were saved, which calls would flip?" Pure CPU over cached artifacts.

Re-runs steps 3 + 6-8 (`decide_call`) for every call with the cached transcript and cached facts. No ASR, no LLM, no
GPU, no file written. Feedback is an argument; this module never reads label files.

Patch (mirrors POST /settings/preview so the UI can reuse its drafts):
  {"thresholds": {"alarm"?, "review"?, "confidence_gate"?},
   "keywords":   {"disable_families": [family, ...]}  |  a full keywords.json document ("families" key),
   "rules":      {"disable": [criterion, ...]}        |  a full rules.yaml document ("rules" key)}
An invalid result (review >= alarm, unknown family, ...) raises `ConfigError`, which the API maps to 422.

Reference for the feedback check is the decision under the *current* config (`baseline`), not the decision the
officer saw, so a verdict stays meaningful after the config moved:
  correct      must keep its decision
  false_alarm  must not become more severe; credit (rank_before - rank_after) / rank_before
  missed       must not become less severe;  credit (rank_after - rank_before) / (2 - rank_before)
Any other movement of a labelled call is a violation.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline import decide as dc
from pipeline import keywords as kw
from pipeline.decide import Config, config_from_dicts, decide_call
from pipeline.keywords import ConfigError
from pipeline.schemas import (CRITERIA, DECISION_RANK, DECISIONS, AnalysisArtifact, DecisionTrace, Fact,
                              FeedbackCheck, FeedbackEntry, FlippedCall, SimulationResult, StageError, Transcript, Versions,
                              Workload, WorkloadPair)

REPO_ROOT = Path(__file__).resolve().parents[1]
THRESHOLD_KEYS = ("alarm", "review", "confidence_gate")
_PATCH_KEYS = ("thresholds", "keywords", "rules")


# --------------------------------------------------------------------------- inputs

@dataclass
class CallInputs:
    """Everything `decide_call` needs for one call, loaded from cache. `facts=None` = extraction failed."""
    transcript: Transcript
    facts: list[Fact] | None
    analysis: AnalysisArtifact | None = None
    stage_errors: list[StageError] = field(default_factory=list)
    versions: Versions | None = None

    @property
    def call_id(self) -> str:
        return self.transcript.call_id

    @property
    def locked(self) -> bool:
        return bool(self.stage_errors) or self.facts is None


def load_inputs(artifacts_dir: Path = REPO_ROOT / "artifacts", out_dir: Path = REPO_ROOT / "out") -> list[CallInputs]:
    """Calls that have a transcript and a decision trace (the trace carries the facts, dropped ones included).
    Stage errors come from out/results/<id>.json when it exists. Unreadable calls are skipped, not fatal."""
    artifacts_dir, out_dir = Path(artifacts_dir), Path(out_dir)
    calls = []
    for tp in sorted((artifacts_dir / "traces").glob("*.json")):
        cid = tp.stem
        try:
            trace = DecisionTrace.from_dict(json.loads(tp.read_text(encoding="utf-8")))
            transcript = Transcript.from_dict(json.loads((artifacts_dir / "transcripts" / f"{cid}.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        analysis = None
        ap = artifacts_dir / "analysis" / cid / "analysis.json"
        if ap.exists():
            try:
                analysis = AnalysisArtifact.from_dict(json.loads(ap.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                analysis = None
        errors: list[StageError] = []
        rp = out_dir / "results" / f"{cid}.json"
        if rp.exists():
            try:
                errors = [StageError(**e) for e in json.loads(rp.read_text(encoding="utf-8")).get("stage_errors", [])]
            except (OSError, ValueError, TypeError):
                errors = []
        calls.append(CallInputs(transcript, trace.facts, analysis, errors, trace.versions))
    return calls


# --------------------------------------------------------------------------- config patching

@dataclass
class RawConfig:
    """The three config documents as plain dicts (what the settings API reads and writes)."""
    keywords: dict
    rules: dict
    thresholds: dict

    def build(self) -> Config:
        return config_from_dicts(self.keywords, self.rules, self.thresholds)


def load_raw(config_dir: Path = dc.CONFIG_DIR) -> RawConfig:
    d = Path(config_dir)
    return RawConfig(json.loads((d / "keywords.json").read_text(encoding="utf-8")),
                     yaml.safe_load((d / "rules.yaml").read_text(encoding="utf-8")) or {},
                     json.loads((d / "thresholds.json").read_text(encoding="utf-8")))


def patch_components(patch: dict | None) -> list[str]:
    """Stable, human-readable list of the independent knobs a patch turns, e.g. ['thresholds.alarm=0.8', 'rules.disable:insider_trading']."""
    p = patch or {}
    out = [f"thresholds.{k}={p['thresholds'][k]}" for k in THRESHOLD_KEYS if k in (p.get("thresholds") or {})]
    k = p.get("keywords") or {}
    out += ["keywords.replace"] if "families" in k else [f"keywords.disable:{f}" for f in k.get("disable_families", [])]
    r = p.get("rules") or {}
    out += ["rules.replace"] if "rules" in r else [f"rules.disable:{c}" for c in r.get("disable", [])]
    return out


def _check_patch(patch: dict, raw: RawConfig) -> None:
    errs = [f"patch.{k}: unknown key (use {_PATCH_KEYS})" for k in patch if k not in _PATCH_KEYS]
    th = patch.get("thresholds") or {}
    errs += [f"patch.thresholds.{k}: unknown key (use {THRESHOLD_KEYS})" for k in th if k not in THRESHOLD_KEYS]
    k = patch.get("keywords") or {}
    if "families" not in k:
        errs += [f"patch.keywords.disable_families: {f!r} is not a configured family" for f in k.get("disable_families", [])
                 if f not in (raw.keywords.get("families") or {})]
        errs += [f"patch.keywords.{x}: unknown key" for x in k if x != "disable_families"]
    r = patch.get("rules") or {}
    if "rules" not in r:
        known = {x.get("criterion") for x in raw.rules.get("rules", [])}
        errs += [f"patch.rules.disable: {c!r} is not a configured rule (use {CRITERIA})" for c in r.get("disable", []) if c not in known]
        errs += [f"patch.rules.{x}: unknown key" for x in r if x != "disable"]
    if errs:
        raise ConfigError(errs)


def patched_docs(raw: RawConfig, patch: dict | None) -> RawConfig:
    """The three documents as they would be saved. Raises ConfigError for an invalid patch (including review >= alarm)."""
    patch = patch or {}
    _check_patch(patch, raw)
    kws, rules, th = copy.deepcopy(raw.keywords), copy.deepcopy(raw.rules), copy.deepcopy(raw.thresholds)
    th.update(patch.get("thresholds") or {})
    k = patch.get("keywords") or {}
    if "families" in k:
        kws = copy.deepcopy(k)
    else:
        for f in k.get("disable_families", []):
            kws["families"].pop(f, None)
    r = patch.get("rules") or {}
    if "rules" in r:
        rules = copy.deepcopy(r)
    else:
        for rule in rules.get("rules", []):
            if rule.get("criterion") in r.get("disable", []):
                rule["enabled"] = False
    out = RawConfig(kws, rules, th)
    out.build()                                           # validates (ConfigError)
    return out


def apply_patch(raw: RawConfig, patch: dict | None) -> Config:
    return patched_docs(raw, patch).build()


def merge_patches(a: dict, b: dict) -> dict:
    """Union of two toggle-style patches (b wins on equal threshold keys)."""
    out: dict = {}
    th = {**(a.get("thresholds") or {}), **(b.get("thresholds") or {})}
    if th:
        out["thresholds"] = th
    fams = sorted(set((a.get("keywords") or {}).get("disable_families", [])) | set((b.get("keywords") or {}).get("disable_families", [])))
    if fams:
        out["keywords"] = {"disable_families": fams}
    rls = sorted(set((a.get("rules") or {}).get("disable", [])) | set((b.get("rules") or {}).get("disable", [])))
    if rls:
        out["rules"] = {"disable": rls}
    return out


def split_patch(patch: dict) -> list[dict]:
    """One single-knob patch per component (full-document replacements stay whole)."""
    out = []
    p = patch or {}
    for k in THRESHOLD_KEYS:
        if k in (p.get("thresholds") or {}):
            out.append({"thresholds": {k: p["thresholds"][k]}})
    kp = p.get("keywords") or {}
    out += [dict(keywords=kp)] if "families" in kp else [{"keywords": {"disable_families": [f]}} for f in kp.get("disable_families", [])]
    rp = p.get("rules") or {}
    out += [dict(rules=rp)] if "rules" in rp else [{"rules": {"disable": [c]}} for c in rp.get("disable", [])]
    return out


def canonical(patch: dict | None) -> str:
    return json.dumps(patch or {}, sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------- metrics

def workload(decisions: list[str]) -> Workload:
    n = len(decisions)
    a, r = decisions.count("alarm"), decisions.count("review")
    per = lambda x: round(100.0 * x / n, 2) if n else 0.0
    return Workload(n, per(a), per(r), per(a + r))


def credit(verdict: str, before: str, after: str) -> tuple[float, bool]:
    """(fix credit in [0, 1], violation?) of one labelled call moving from `before` to `after`."""
    rb, ra = DECISION_RANK[before], DECISION_RANK[after]
    if verdict == "correct":
        return 0.0, ra != rb
    if verdict == "false_alarm":
        return ((rb - ra) / rb if rb and ra < rb else 0.0), ra > rb
    return ((ra - rb) / (2 - rb) if rb < 2 and ra > rb else 0.0), ra < rb


# --------------------------------------------------------------------------- the simulator

class Simulator:
    """Holds the inputs and the caches, so many patches (the suggestion search) stay cheap.

    Keyword hits are cached per (call, keyword document): a threshold or rule patch never re-runs the fuzzy matcher.
    """

    def __init__(self, inputs: list[CallInputs], raw: RawConfig | None = None, feedback: dict[str, FeedbackEntry] | None = None,
                 validate: bool = True):
        self.validate = validate
        self.inputs = list(inputs)
        self.raw = raw or load_raw()
        self.feedback = {c: e for c, e in (feedback or {}).items() if c in {i.call_id for i in self.inputs}}
        self.base_config = self.raw.build()
        self._hits: dict[tuple[str, str], list] = {}
        self._configs: dict[str, Config] = {}
        self._kwkeys: dict[str, str] = {}
        self._traces: dict[tuple[str, str], DecisionTrace] = {}
        self.baseline = {i.call_id: self.trace(i, "{}") for i in self.inputs}

    # -- plumbing
    def config(self, key: str) -> Config:
        if key not in self._configs:
            self._configs[key] = apply_patch(self.raw, json.loads(key))
        return self._configs[key]

    def _kwkey(self, key: str, cfg: Config) -> str:
        if key not in self._kwkeys:
            self._kwkeys[key] = json.dumps([{n: [f.terms, f.variants] for n, f in cfg.keywords.families.items()},
                                            cfg.keywords.fuzzy_threshold, cfg.keywords.min_fuzzy_len], sort_keys=True, ensure_ascii=False)
        return self._kwkeys[key]

    def trace(self, call: CallInputs, key: str) -> DecisionTrace:
        """Decision trace of one call under the patch `key` (canonical JSON). Cached."""
        ck = (call.call_id, key)
        if ck not in self._traces:
            cfg = self.config(key)
            hk = (call.call_id, self._kwkey(key, cfg))
            if hk not in self._hits:
                self._hits[hk] = kw.find_hits(call.transcript, cfg.keywords)
            self._traces[ck] = decide_call(call.transcript, call.facts, call.analysis, cfg, call.stage_errors or None,
                                           call.versions, hits=self._hits[hk], validate=self.validate)
        return self._traces[ck]

    # -- evaluation
    def decisions(self, patch: dict | None) -> dict[str, str]:
        key = canonical(patch)
        return {i.call_id: self.trace(i, key).decision for i in self.inputs}

    def check_feedback(self, after: dict[str, str]) -> FeedbackCheck:
        fixed, unchanged, bad, total = [], [], [], 0.0
        for cid, fb in sorted(self.feedback.items()):
            c, violated = credit(fb.verdict, self.baseline[cid].decision, after[cid])
            total += c
            (bad if violated else fixed if c > 0 else unchanged).append(cid)
        return FeedbackCheck(len(self.feedback), round(total, 6), fixed, unchanged, bad)

    def run(self, patch: dict | None, explain: bool = True) -> SimulationResult:
        patch = patch or {}
        key = canonical(patch)
        cfg = self.config(key)                             # ConfigError for an invalid patch
        after_tr = {i.call_id: self.trace(i, key) for i in self.inputs}
        before = [self.baseline[i.call_id].decision for i in self.inputs]
        after = [after_tr[i.call_id].decision for i in self.inputs]
        wb, wa = workload(before), workload(after)
        parts = split_patch(patch)
        flipped = []
        for i in self.inputs:
            tb, ta = self.baseline[i.call_id], after_tr[i.call_id]
            if tb.decision == ta.decision:
                continue
            fb = self.feedback.get(i.call_id)
            flipped.append(FlippedCall(
                i.call_id, tb.decision, ta.decision, "up" if DECISION_RANK[ta.decision] > DECISION_RANK[tb.decision] else "down",
                tb.risk_score, ta.risk_score, tb.confidence, ta.confidence, tb.decision_path, ta.decision_path,
                _reasons(tb, ta) if explain else [],
                _attribute(self, i, ta.decision, parts) if explain else [],
                fb.verdict if fb else None))
        flipped.sort(key=lambda f: (f.direction != "up", f.call_id))
        return SimulationResult(
            patch=patch, baseline_version=self.base_config.rules_version, patched_version=cfg.rules_version, n_calls=len(self.inputs),
            n_locked=sum(1 for i in self.inputs if i.locked),
            counts={"before": {d: before.count(d) for d in DECISIONS}, "after": {d: after.count(d) for d in DECISIONS}},
            workload=WorkloadPair(wb, wa, round(wa.flagged_per_100 - wb.flagged_per_100, 2)), flipped=flipped,
            feedback_check=self.check_feedback(dict(zip((i.call_id for i in self.inputs), after))) if self.feedback else None,
            is_mock=any(i.transcript.is_mock for i in self.inputs))


def _reasons(tb: DecisionTrace, ta: DecisionTrace) -> list[str]:
    th = ta.thresholds
    out = [f"decision path {tb.decision_path} → {ta.decision_path}"]
    if ta.decision_path == "alarm":
        out.append(f"risk {ta.risk_score:.2f} ≥ alarm threshold {th.alarm:.2f}, with valid evidence and confidence {ta.confidence:.2f} ≥ gate {th.confidence_gate:.2f}")
    elif ta.decision_path == "review_band":
        out.append(f"risk {ta.risk_score:.2f} is in the review band [{th.review:.2f}, {th.alarm:.2f})")
    elif ta.decision_path == "no_alert":
        out.append(f"risk {ta.risk_score:.2f} < review threshold {th.review:.2f}")
    elif ta.decision_path == "low_confidence":
        out.append(f"confidence {ta.confidence:.2f} < gate {th.confidence_gate:.2f}")
    if tb.risk_score != ta.risk_score:
        out.append(f"risk {tb.risk_score:.2f} → {ta.risk_score:.2f}")
    if tb.confidence is not None and ta.confidence is not None and abs(tb.confidence - ta.confidence) >= 0.005:
        out.append(f"confidence {tb.confidence:.2f} → {ta.confidence:.2f}")
    rb = {r.criterion: r for r in tb.rules}
    ra = {r.criterion: r for r in ta.rules}
    for c in sorted(set(rb) | set(ra)):
        if c not in ra:
            out.append(f"rule {c} no longer evaluated (disabled)")
        elif c in rb and abs(rb[c].risk - ra[c].risk) >= 0.005:
            out.append(f"rule {c} risk {rb[c].risk:.2f} → {ra[c].risk:.2f}")
    if len(tb.keyword_hits) != len(ta.keyword_hits):
        out.append(f"keyword hits {len(tb.keyword_hits)} → {len(ta.keyword_hits)}")
    return out


def _attribute(sim: Simulator, call: CallInputs, target: str, parts: list[dict]) -> list[str]:
    """Components that alone reproduce the flip. A single-knob patch is its own cause; otherwise ablate each knob."""
    if len(parts) <= 1:
        return patch_components(parts[0]) if parts else []
    before = sim.baseline[call.call_id].decision
    solo = [patch_components(p)[0] for p in parts if sim.trace(call, canonical(p)).decision == target != before]
    return solo or ["combination of " + ", ".join(c for p in parts for c in patch_components(p))]


def simulate(inputs: list[CallInputs], patch: dict | None, raw: RawConfig | None = None,
             feedback: dict[str, FeedbackEntry] | None = None) -> SimulationResult:
    """One-shot convenience wrapper around `Simulator.run`."""
    return Simulator(inputs, raw, feedback).run(patch)
