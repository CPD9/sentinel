// MOCK only (fixtures mode). A client-side approximation of POST /api/simulate over fixtures/whatif_calls.json.
// Pure functions, no fetching. The real simulator is pipeline/simulate.py; api mode never uses this file.
// What is approximate: a threshold-only draft is re-decided from each call's risk, confidence and decision path;
// a draft with a keyword family or rule switched off uses the precomputed single-switch decisions (several switches
// take the least severe of them, and thresholds are ignored then). An exact stored result is used when the draft equals a suggestion.
import type {
  Decision, FeedbackCheck, FeedbackEntry, FlippedCall, Patch, SimulationResult, Thresholds, Verdict, Workload,
} from "./types";
import { DECISION_RANK, DECISIONS } from "./types";

export interface WhatifRow {
  call_id: string; decision: Decision; decision_path: string; risk_score: number; confidence: number | null;
  locked: boolean; if_disabled: Record<string, Decision>;
}
export interface WhatifCalls {
  is_mock: boolean; config_version: string; thresholds: Thresholds; components: string[]; calls: WhatifRow[];
}

const THRESHOLD_KEYS = ["alarm", "review", "confidence_gate"] as const;

/** Same component names as pipeline/simulate.patch_components. */
export function patchComponents(p: Patch | null | undefined): string[] {
  const out: string[] = [];
  const th = p?.thresholds ?? {};
  for (const k of THRESHOLD_KEYS) if (th[k] !== undefined) out.push(`thresholds.${k}=${th[k]}`);
  const kw = p?.keywords;
  if (kw) out.push(...("families" in kw ? ["keywords.replace"] : kw.disable_families.map((f) => `keywords.disable:${f}`)));
  const rl = p?.rules;
  if (rl) out.push(...("rules" in rl ? ["rules.replace"] : rl.disable.map((c) => `rules.disable:${c}`)));
  return out;
}
export const samePatch = (a: Patch, b: Patch) => {
  const x = patchComponents(a).sort().join("|"), y = patchComponents(b).sort().join("|");
  return x === y;
};

export function creditFor(verdict: Verdict, before: Decision, after: Decision): { credit: number; violation: boolean } {
  const rb = DECISION_RANK[before], ra = DECISION_RANK[after];
  if (verdict === "correct") return { credit: 0, violation: ra !== rb };
  if (verdict === "false_alarm") return { credit: rb > 0 && ra < rb ? (rb - ra) / rb : 0, violation: ra > rb };
  return { credit: rb < 2 && ra > rb ? (ra - rb) / (2 - rb) : 0, violation: ra < rb };
}

export function workloadOf(decisions: Decision[]): Workload {
  const n = decisions.length;
  const per = (x: number) => (n ? Math.round((10000 * x) / n) / 100 : 0);
  const a = decisions.filter((d) => d === "alarm").length, r = decisions.filter((d) => d === "review").length;
  return { n, alarms_per_100: per(a), reviews_per_100: per(r), flagged_per_100: per(a + r) };
}

function decideFromRow(r: WhatifRow, th: Thresholds): { decision: Decision; path: string } {
  if (r.locked || ["stage_error", "missing_evidence", "contradictory_evidence"].includes(r.decision_path)) return { decision: r.decision, path: r.decision_path };
  if (r.confidence != null && r.confidence < th.confidence_gate && r.risk_score >= th.review) return { decision: "review", path: "low_confidence" };
  if (r.risk_score >= th.alarm) return { decision: "alarm", path: "alarm" };
  if (r.risk_score >= th.review) return { decision: "review", path: "review_band" };
  return { decision: "no_alert", path: "no_alert" };
}

export function approxSimulate(patch: Patch, data: WhatifCalls, feedback: Map<string, FeedbackEntry>): SimulationResult {
  const th: Thresholds = { ...data.thresholds, ...(patch.thresholds ?? {}) } as Thresholds;
  const comps = patchComponents(patch);
  const toggles = comps.filter((c) => c.startsWith("keywords.disable:") || c.startsWith("rules.disable:"));
  const after: { row: WhatifRow; decision: Decision; path: string }[] = data.calls.map((row) => {
    if (row.locked) return { row, decision: row.decision, path: row.decision_path };
    if (toggles.length) {
      const ds = toggles.map((t) => row.if_disabled[t] ?? row.decision);
      const least = ds.reduce((m, d) => (DECISION_RANK[d] < DECISION_RANK[m] ? d : m), ds[0]);
      return { row, decision: least, path: least === row.decision ? row.decision_path : "approx" };
    }
    const d = decideFromRow(row, th);
    return { row, decision: d.decision, path: d.path };
  });
  const flipped: FlippedCall[] = after.filter((a) => a.decision !== a.row.decision).map(({ row, decision, path }) => ({
    call_id: row.call_id, before: row.decision, after: decision,
    direction: (DECISION_RANK[decision] > DECISION_RANK[row.decision] ? "up" : "down") as "up" | "down",
    risk_before: row.risk_score, risk_after: row.risk_score, confidence_before: row.confidence, confidence_after: row.confidence,
    path_before: row.decision_path, path_after: path,
    reasons: [`[MOCK approximation] ${row.decision_path} → ${path}`, toggles.length ? `switched off: ${toggles.map((t) => t.split(":")[1]).join(", ")}` : `risk ${row.risk_score.toFixed(2)} against alarm ${th.alarm.toFixed(2)} / review ${th.review.toFixed(2)}`],
    attributed_to: comps, feedback_verdict: feedback.get(row.call_id)?.verdict ?? null,
  })).sort((a, b) => (a.direction === b.direction ? a.call_id.localeCompare(b.call_id) : a.direction === "up" ? -1 : 1));
  const count = (ds: Decision[]) => Object.fromEntries(DECISIONS.map((d) => [d, ds.filter((x) => x === d).length])) as Record<Decision, number>;
  const before = data.calls.map((r) => r.decision), afterD = after.map((a) => a.decision);
  const wb = workloadOf(before), wa = workloadOf(afterD);

  let check: FeedbackCheck | null = null;
  const known = [...feedback.values()].filter((f) => data.calls.some((c) => c.call_id === f.call_id));
  if (known.length) {
    check = { n_feedback: known.length, fix_credit: 0, fixed: [], unchanged: [], violations: [] };
    for (const f of known.sort((a, b) => a.call_id.localeCompare(b.call_id))) {
      const i = data.calls.findIndex((c) => c.call_id === f.call_id);
      const { credit, violation } = creditFor(f.verdict, before[i], afterD[i]);
      check.fix_credit = Math.round((check.fix_credit + credit) * 1e6) / 1e6;
      (violation ? check.violations : credit > 0 ? check.fixed : check.unchanged).push(f.call_id);
    }
  }
  return {
    patch, baseline_version: data.config_version, patched_version: comps.length ? `${data.config_version}~draft` : data.config_version,
    n_calls: data.calls.length, n_locked: data.calls.filter((c) => c.locked).length,
    counts: { before: count(before), after: count(afterD) },
    workload: { before: wb, after: wa, delta_flagged_per_100: Math.round((wa.flagged_per_100 - wb.flagged_per_100) * 100) / 100 },
    flipped, feedback_check: check, is_mock: true, schema_version: 1,
  };
}
