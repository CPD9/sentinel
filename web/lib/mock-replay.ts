// MOCK ONLY. Builds ProcessingEvent sequences for fixture calls that have no events file, and defines the
// replay pacing. Real events come from the API (docs/API.md); nothing here runs in api mode.
import type { CallResult, DecisionTrace, ProcessingEvent, Stage } from "./types";

const ORDER: Stage[] = ["asr", "diarize", "keywords", "extract", "validate", "rules", "confidence", "decide", "narrate", "snippets"];

function base(call_id: string, seq: number, t0: number, offset: number): Pick<ProcessingEvent, "seq" | "call_id" | "ts"> {
  return { seq, call_id, ts: new Date(t0 + offset * 1000).toISOString().replace(/\.\d+Z$/, "Z") };
}

const blank = { stage: null, elapsed_s: null, cached: null, message: null, decision: null } as const;

/** Events for a finished call, built from trace timings (002) or its stage errors (004). */
export function synthFinishedEvents(call_id: string, result: CallResult, trace: DecisionTrace | null): ProcessingEvent[] {
  const t0 = Date.parse("2026-10-10T14:00:00Z");
  const out: ProcessingEvent[] = [];
  let seq = 1;
  let clock = 0;
  const push = (e: Partial<ProcessingEvent> & Pick<ProcessingEvent, "event">, dt = 0) => {
    clock += dt;
    out.push({ ...blank, ...base(call_id, seq++, t0, clock), ...e });
  };
  push({ event: "job_queued", message: "[MOCK] synthesised from fixtures" });
  const failed = new Map(result.stage_errors.map((e) => [e.stage, e.message]));
  for (const stage of ORDER) {
    const took = trace?.timings_s[stage];
    if (failed.has(stage)) {
      push({ event: "stage_started", stage });
      push({ event: "stage_failed", stage, elapsed_s: 2.1, message: failed.get(stage)! }, 2.1);
      continue;
    }
    if (trace ? took == null : stage !== "decide") continue;
    push({ event: "stage_started", stage });
    push({ event: "stage_finished", stage, elapsed_s: took ?? 0, cached: false }, took ?? 0);
  }
  push({ event: "job_finished", decision: result.decision });
  return out;
}

/** A call that is still processing: ASR and diarize done, extract running. Never finishes (MOCK). */
export function synthRunningEvents(call_id: string): ProcessingEvent[] {
  const t0 = Date.now() - 50_000;
  const rows: Partial<ProcessingEvent>[] = [
    { event: "job_queued", message: "[MOCK] call_MOCK_003 queued" },
    { event: "stage_started", stage: "asr" },
    { event: "stage_finished", stage: "asr", elapsed_s: 28.2, cached: false },
    { event: "stage_started", stage: "diarize" },
    { event: "stage_finished", stage: "diarize", elapsed_s: 5.4, cached: false },
    { event: "stage_started", stage: "keywords" },
    { event: "stage_finished", stage: "keywords", elapsed_s: 0.02, cached: false },
    { event: "stage_started", stage: "extract" },
  ];
  return rows.map((r, i) => ({ ...blank, ...base(call_id, i + 1, t0, i * 6), ...r }) as ProcessingEvent);
}

/** Delay before delivering `next` after `prev`: compressed real time, between 150 ms and 1.4 s. */
export function replayDelayMs(prev: ProcessingEvent | null, next: ProcessingEvent): number {
  if (!prev) return 250;
  const dt = (Date.parse(next.ts) - Date.parse(prev.ts)) / 1000;
  return Math.min(1400, Math.max(150, (dt * 1000) / 10));
}
