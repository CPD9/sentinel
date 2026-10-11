// Copilot fetch helpers (app/copilot-api). Answers stream as NDJSON events; every claim has already passed the
// pipeline's evidence checker. Chat history lives only in the caller's React state.
import { audioUrl } from "@/lib/data";

export type CopilotCitation = { call_id: string; segment_id: string; speaker: string; start_s: number | null; end_s: number | null; text: string; quote: string };
export type CopilotClaim = { type: "claim"; text: string; citations: CopilotCitation[]; dropped_citations: number };
export type CopilotEvent =
  | { type: "queued" }
  | { type: "start"; provider: string; model: string; self_hosted: boolean }
  | CopilotClaim
  | { type: "dropped"; reason: string }
  | { type: "retry" }
  | { type: "not_in_call" }
  | { type: "done"; kept: number; dropped: number; wall_ms: number }
  | { type: "error"; detail: string };

export type HistoryTurn = { q: string; claims: { claim: string; call_id?: string; segment_id: string; quote: string }[] };
export type AskBody = { scope: "call"; call_id: string; question: string; history?: HistoryTurn[] } | { scope: "all"; question: string; history?: HistoryTurn[] };

const URL_ASK = "/copilot-api";

export async function askCopilot(body: AskBody, onEvent: (e: CopilotEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(URL_ASK, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal, cache: "no-store" });
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`;
    try { detail = ((await res.json()) as { detail?: string }).detail ?? detail; } catch { /* not JSON */ }
    onEvent({ type: "error", detail });
    return;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) { try { onEvent(JSON.parse(line) as CopilotEvent); } catch { /* partial or foreign line */ } }
    }
  }
}

export type PatternHit = { call_id: string; segment_id: string | null; start_s: number | null; quote: string };
export type PatternRow = { entity: string; n_calls: number; hits: PatternHit[] };
export type Patterns = {
  calls: Record<string, { decision: string | null; risk_score: number | null }>;
  criteria: PatternRow[]; securities: PatternRow[]; account_types: PatternRow[]; recipients: PatternRow[];
  phrases: { phrase: string; calls: PatternHit[] }[]; method: string;
};

export async function getPatterns(): Promise<Patterns> {
  const res = await fetch(`${URL_ASK}?patterns=1`, { cache: "no-store" });
  if (!res.ok) throw new Error(((await res.json().catch(() => null)) as { detail?: string } | null)?.detail ?? `HTTP ${res.status}`);
  return (await res.json()) as Patterns;
}

/** Audio of one call from second `start` (the run-api serves it with Range support); null without audio. */
export function clipUrl(callId: string, start: number | null, end: number | null): string | null {
  const base = audioUrl(callId);
  if (!base || start == null) return base;
  return `${base}#t=${Math.max(0, start - 1).toFixed(1)}${end != null ? `,${(end + 1).toFixed(1)}` : ""}`;
}
