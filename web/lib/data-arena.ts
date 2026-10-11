// Model arena: fetch helpers for app/arena-data (scripts/arena.py output) + the officer's duel votes and Elo.
// Votes are stored ONLY in this browser (localStorage); Elo is recomputed from the vote log, so it is deterministic.
import { ApiError } from "./data";
import type { Decision } from "./types";

export interface ArenaRow {
  slug: string; model: string; provider: string; self_hosted: boolean;
  n: number; n_positive: number; errors: number; error_calls: string[];
  auc: number | null; auc_ci95: [number | null, number | null]; auc_by_split: Record<string, number | null>;
  false_alarms: number; missed: number; tp: number; tn: number; balanced_accuracy: number;
  esc_precision: number | null; esc_recall: number | null; flagged: number;
  citations_valid: number; citations_total: number; citation_validity: number | null; flagged_without_valid_citation: number;
  latency_ms_median: number | null; latency_ms_p90: number | null; latency_n: number;
  cost_usd: number | null; cost_calls: number; cost_note: string;
}
export interface ArenaLeaderboard { generated: string; prompt_version: string; n_calls: number; mode: string; note: string; rows: ArenaRow[] }

export interface ArenaCitation {
  segment_id: string | null; speaker: string | null; quote: string | null; valid: boolean; drop_reason: string | null;
  text: string | null; start_s: number | null; end_s: number | null;
}
export interface ArenaVerdict { decision: Decision; risk: number; criterion: string | null; reason: string | null; citations: ArenaCitation[] }
export interface ArenaPool { prompt_version: string; models: string[]; calls: Record<string, Record<string, ArenaVerdict>> }
export interface ArenaTranscript { call_id: string; segments: { id: string; text: string; start_s: number; end_s: number }[] }

async function get<T>(qs: string): Promise<T> {
  const res = await fetch(`/arena-data?${qs}`, { cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = ((await res.json()) as { detail?: string }).detail ?? detail; } catch { /* keep statusText */ }
    throw new ApiError(res.status, res.status === 404 ? "not_found" : "internal", detail);
  }
  return (await res.json()) as T;
}

export const getArenaLeaderboard = () => get<ArenaLeaderboard>("f=leaderboard");
export const getArenaPool = () => get<ArenaPool>("f=pool");
export const getArenaTranscript = (callId: string) => get<ArenaTranscript>(`transcript=${encodeURIComponent(callId)}`);

// ------------------------------------------------------------------ votes + Elo (local only)
export type VoteOutcome = "a" | "b" | "tie" | "both_bad";
export interface Vote { call_id: string; a: string; b: string; outcome: VoteOutcome; at: string }

const VOTES_KEY = "sentinel.arena.votes.v1";
export const ELO_START = 1000;
const ELO_K = 32;

export function loadVotes(): Vote[] {
  try {
    const raw = window.localStorage.getItem(VOTES_KEY);
    const v = raw ? (JSON.parse(raw) as Vote[]) : [];
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export function saveVotes(votes: Vote[]): void {
  try { window.localStorage.setItem(VOTES_KEY, JSON.stringify(votes)); } catch { /* private mode: votes live in memory */ }
}

/** Elo from the vote log in order. "both bad" moves nobody (no preference); "tie" scores 0.5 each. */
export function computeElo(models: string[], votes: Vote[]): Record<string, { elo: number; games: number }> {
  const r: Record<string, { elo: number; games: number }> = Object.fromEntries(models.map((m) => [m, { elo: ELO_START, games: 0 }]));
  for (const v of votes) {
    if (v.outcome === "both_bad") continue;
    const a = (r[v.a] ??= { elo: ELO_START, games: 0 });
    const b = (r[v.b] ??= { elo: ELO_START, games: 0 });
    const ea = 1 / (1 + 10 ** ((b.elo - a.elo) / 400));
    const sa = v.outcome === "a" ? 1 : v.outcome === "b" ? 0 : 0.5;
    a.elo += ELO_K * (sa - ea);
    b.elo += ELO_K * ((1 - sa) - (1 - ea));
    a.games += 1;
    b.games += 1;
  }
  return r;
}
