"""Ranked config suggestions from officer feedback: the smallest change that fixes the most flagged false alarms / misses.

Input is ONLY the officer's verdicts (`false_alarm | missed | correct`, see pipeline/feedback.py) plus the cached
call artifacts. Nothing here reads the held-out answer key, and nothing here applies a change: a Suggestion is a patch
(pipeline/simulate.py format) with its simulated effect, for a human to preview and apply.

Search space: each threshold on a 0.01 grid, each keyword family switched off, each enabled rule switched off, then
combinations of the useful ones (any three knobs), plus a joint alarm + review grid because a pair such as review 0.86
under alarm 0.87 is valid although review 0.86 alone is not. Every candidate is verified with the
real `decide_call` through `Simulator`, never inferred.

Hard constraints (candidate is discarded): a call marked `correct` changes decision, or any labelled call moves the wrong
way (see simulate.credit).
Ranking: most fix credit, then fewest unlabelled calls flipped, fewest knobs, smallest threshold distance, lowest workload.
A candidate is dropped when a strictly smaller change (a subset of its knobs) does at least as well; candidates that give
the same decision for every call collapse to the best-ranked one.
"""
from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass

from pipeline.feedback import now_ts
from pipeline.keywords import ConfigError
from pipeline.schemas import (VERDICTS, FeedbackEntry, Suggestion, SuggestionsResponse)
from pipeline.simulate import (THRESHOLD_KEYS, CallInputs, RawConfig, Simulator, canonical, merge_patches, patch_components)

ZERO_POOL = 6         # best zero-credit singles allowed into pairs
PAIR_RISKS = 8        # flagged-verdict risk levels used for the joint alarm + review grid
POOL = 12             # best single changes combined into pairs / triples
CAVEAT = ("Fitted to {n} officer verdict(s) on this set of calls; not validated on unseen calls. "
          "Preview the effect and review the flipped calls before applying.")


@dataclass
class _Cand:
    patch: dict
    comps: frozenset
    vec: tuple
    credit: float
    violated: bool
    collateral: list
    distance: float
    flagged_delta: float

    @property
    def rank_key(self):
        return (-round(self.credit, 6), len(self.collateral), len(self.comps), round(self.distance, 6), self.flagged_delta, canonical(self.patch))


def _knob(comp: str) -> str:
    return comp.split("=")[0]


class _Search:
    def __init__(self, sim: Simulator):
        self.sim = sim
        self.ids = [i.call_id for i in sim.inputs]
        self.base_vec = tuple(sim.baseline[c].decision for c in self.ids)
        self.base_flagged = sum(d != "no_alert" for d in self.base_vec)
        self.cur = sim.base_config.thresholds
        self._seen: dict[str, _Cand | None] = {}

    def candidate(self, patch: dict) -> _Cand | None:
        key = canonical(patch)
        if key in self._seen:
            return self._seen[key]
        try:
            dec = self.sim.decisions(patch)
        except ConfigError:
            self._seen[key] = None
            return None
        fc = self.sim.check_feedback(dec)
        vec = tuple(dec[c] for c in self.ids)
        th = patch.get("thresholds") or {}
        # A toggle removes a whole detection capability, so it counts as the largest possible threshold move (1.0):
        # at equal effect a nudged threshold beats switching a family or rule off.
        dist = sum(abs(th[k] - getattr(self.cur, k)) for k in th) + sum(c.startswith(("keywords.", "rules.")) for c in patch_components(patch))
        cand = _Cand(patch, frozenset(patch_components(patch)), vec, fc.fix_credit, bool(fc.violations),
                     [c for c, d in zip(self.ids, vec) if d != self.sim.baseline[c].decision and c not in self.sim.feedback],
                     dist, round(100.0 * (sum(d != "no_alert" for d in vec) - self.base_flagged) / max(len(vec), 1), 2))
        self._seen[key] = cand
        return cand

    def singles(self) -> list[_Cand]:
        patches = []
        for k in THRESHOLD_KEYS[:3]:                     # the numeric thresholds (keyword_review is a switch)
            cur = round(getattr(self.cur, k), 2)
            patches += [{"thresholds": {k: v}} for v in (round(i / 100, 2) for i in range(101)) if v != cur]
        patches += [{"keywords": {"disable_families": [f]}} for f in sorted(self.sim.raw.keywords.get("families") or {})]
        patches += [{"rules": {"disable": [r["criterion"]]}} for r in self.sim.raw.rules.get("rules", []) if r.get("enabled", True)]
        out = [c for c in map(self.candidate, patches) if c is not None and c.vec != self.base_vec]
        # Equivalent thresholds (same decision for every call): keep the one closest to the current value.
        best: dict[tuple, _Cand] = {}
        for c in sorted(out, key=lambda c: (c.distance, canonical(c.patch))):
            best.setdefault((frozenset(_knob(x) for x in c.comps), c.vec), c)
        return list(best.values())

    def combos(self, singles: list[_Cand]) -> list[_Cand]:
        ok = [c for c in singles if not c.violated]
        pos = sorted((c for c in ok if c.credit > 0), key=lambda c: c.rank_key)[:POOL]
        # A change that does nothing for the verdicts alone can still enable another one (e.g. a lower alarm bar plus a rule off).
        zero = sorted((c for c in ok if c.credit == 0), key=lambda c: (len(c.collateral), c.distance, canonical(c.patch)))[:ZERO_POOL]
        out = []
        for r, pool in ((2, pos + zero), (3, pos)):
            for combo in itertools.combinations(pool, r):
                knobs = [_knob(x) for c in combo for x in c.comps]
                if len(set(knobs)) != len(knobs):
                    continue
                patch = {}
                for c in combo:
                    patch = merge_patches(patch, c.patch)
                cand = self.candidate(patch)
                if cand is not None and cand.vec != self.base_vec:
                    out.append(cand)
        return out

    def threshold_pairs(self) -> list[_Cand]:
        """Joint (alarm, review) moves. Neither value need be valid alone (review 0.86 under alarm 0.70 is not), so these never
        appear among the singles. Values sit at and just above the risk of each call the officer called wrong, which is where
        a pair can change such a call."""
        risks = sorted({round(self.sim.baseline[c].risk_score, 2) for c, fb in self.sim.feedback.items() if fb.verdict != "correct"})[:PAIR_RISKS]
        vals = sorted({min(1.0, v) for r in risks for v in (r, round(r + 0.01, 2), round(r + 0.02, 2))})
        cur_a, cur_r = round(self.cur.alarm, 2), round(self.cur.review, 2)
        patches = [{"thresholds": {"alarm": a, "review": r}} for a in vals for r in vals if r < a and a != cur_a and r != cur_r]
        return [c for c in map(self.candidate, patches) if c is not None and c.vec != self.base_vec]


def _title(patch: dict, cur) -> str:
    parts = []
    for k, v in (patch.get("thresholds") or {}).items():
        old = getattr(cur, k)
        parts.append(f"{'raise' if v > old else 'lower'} {k.replace('_', ' ')} {'threshold ' if k != 'confidence_gate' else ''}{old:.2f} → {v:.2f}")
    parts += [f"turn off keyword family '{f}'" for f in (patch.get("keywords") or {}).get("disable_families", [])]
    parts += [f"turn off rule '{c}'" for c in (patch.get("rules") or {}).get("disable", [])]
    text = " + ".join(parts)
    return text[:1].upper() + text[1:]


def _rank(search: _Search) -> list[_Cand]:
    singles = search.singles()
    cands = [c for c in singles + search.combos(singles) + search.threshold_pairs() if c.credit > 0 and not c.violated]
    cands.sort(key=lambda c: c.rank_key)
    kept: list[_Cand] = []
    for c in cands:
        if any(k.vec == c.vec for k in kept):
            continue
        # same knobs as a better candidate, no more credit and no fewer side effects: a near-duplicate (e.g. 0.55 vs 0.56)
        if any({_knob(x) for x in k.comps} == {_knob(x) for x in c.comps} and k.credit >= c.credit - 1e-9
               and set(k.collateral) <= set(c.collateral) for k in kept):
            continue
        if any(o.comps < c.comps and o.credit >= c.credit - 1e-9 and len(o.collateral) <= len(c.collateral) for o in cands):
            continue
        kept.append(c)
    return kept


def suggest(inputs: list[CallInputs], feedback: dict[str, FeedbackEntry], raw: RawConfig | None = None,
            max_results: int = 5, sim: Simulator | None = None) -> list[Suggestion]:
    # The search runs without per-trace schema checks (speed); the returned suggestions are re-run with them.
    sim = sim or Simulator(inputs, raw, feedback, validate=False)
    checked = Simulator(inputs, raw, feedback, validate=True)
    if not any(fb.verdict != "correct" for fb in sim.feedback.values()):
        return []
    version = sim.base_config.rules_version
    out = []
    for c in _rank(_Search(sim))[:max_results]:
        eff = checked.run(c.patch)
        fc = eff.feedback_check
        actionable = [cid for cid, fb in sorted(sim.feedback.items()) if fb.verdict != "correct"]
        not_fixed = [cid for cid in actionable if cid not in fc.fixed]
        pid = hashlib.sha256((canonical(c.patch) + version).encode()).hexdigest()[:12]
        partly = [f.call_id for f in eff.flipped if f.call_id in fc.fixed and f.after != "no_alert" and f.feedback_verdict == "false_alarm"
                  or f.call_id in fc.fixed and f.after != "alarm" and f.feedback_verdict == "missed"]
        why = (f"Moves {len(fc.fixed)} of {len(actionable)} flagged verdict(s) the right way ({', '.join(fc.fixed)}), fix credit {fc.fix_credit:g} of {len(actionable)}"
               + (f"; {', '.join(partly)} only part of the way (alarm to review, or no_alert to review)" if partly else "")
               + f". {len(c.collateral)} unlabelled call(s) change decision; flagged calls per 100: "
               f"{eff.workload.before.flagged_per_100:g} → {eff.workload.after.flagged_per_100:g}. "
               f"No call marked correct changes.")
        crit = [c.split(":", 1)[1] for c in patch_components(c.patch) if c.startswith("rules.disable:")]
        fams = [c.split(":", 1)[1] for c in patch_components(c.patch) if c.startswith("keywords.disable:")]
        if crit or fams:
            why += (" Warning: this switches off " + " and ".join(
                [f"rule {x}" for x in crit] + [f"keyword family {x}" for x in fams]) + " for every call, including real cases.")
        out.append(Suggestion(pid, c.patch, _title(c.patch, sim.base_config.thresholds), why, version, len(c.comps),
                              fc.fix_credit, list(fc.fixed), not_fixed, c.collateral, eff))
    return out


def suggestions_response(inputs: list[CallInputs], feedback: dict[str, FeedbackEntry], raw: RawConfig | None = None,
                         max_results: int = 5) -> SuggestionsResponse:
    """The body of GET /api/suggestions. An empty list always carries a reason."""
    sim = Simulator(inputs, raw, feedback, validate=False)
    counts = {v: sum(fb.verdict == v for fb in sim.feedback.values()) for v in VERDICTS}
    sugg = suggest(inputs, feedback, raw, max_results, sim)
    reason = None
    if not sugg:
        if not sim.feedback:
            reason = "No officer feedback yet. Mark calls as false alarm, missed or correct to get suggestions."
        elif counts["false_alarm"] + counts["missed"] == 0:
            reason = "Only 'correct' verdicts so far, so there is nothing to fix."
        elif all(_already_fixed(sim, cid, fb.verdict) for cid, fb in sim.feedback.items() if fb.verdict != "correct"):
            reason = "Every flagged false alarm / miss is already resolved by the current configuration."
        else:
            reason = ("No single change or small combination fixes a flagged call without changing a call marked correct "
                      "or moving another labelled call the wrong way.")
    return SuggestionsResponse(now_ts(), sim.base_config.rules_version, len(sim.feedback), counts, sugg,
                               CAVEAT.format(n=len(sim.feedback)), reason, any(i.transcript.is_mock for i in inputs))


def _already_fixed(sim: Simulator, cid: str, verdict: str) -> bool:
    d = sim.baseline[cid].decision
    return (verdict == "false_alarm" and d == "no_alert") or (verdict == "missed" and d == "alarm")
