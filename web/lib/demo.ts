// Demo mode for the jury: a keyboard-driven path (→ / ←) over the SAME real screens, hitting the four required moments
// in order. No separate pages and no staged data: each step is a real URL plus one line telling the presenter what to show.
// The call ids default to the final multi-check judge run (mc_0656_final); set NEXT_PUBLIC_DEMO_ALERT / NEXT_PUBLIC_DEMO_HARMLESS for another run.
import { useEffect } from "react";

export const DEMO_ALERT = process.env.NEXT_PUBLIC_DEMO_ALERT || "call_041";   // insider trading before the quarterly figures: the AI judge alert, as in the case brief
export const DEMO_HARMLESS = process.env.NEXT_PUBLIC_DEMO_HARMLESS || "call_040";   // clean; the alert's own insider words (Quartalszahlen, vor der Meldung) in 6 passages, about public reports: No alert

export interface DemoStep { href: string; moment: string; title: string; say: string; live?: string }

/** Optional proof of "no manual steps" for moment 1: one live run in a terminal on a renamed WAV (a new neutral id,
 *  so the shared artifacts of the recorded run are untouched). The recorded replay is the default. */
export const LIVE_RUN = "mkdir -p /tmp/live && cp <dev wav> /tmp/live/demo_call.wav && ASR_MODEL_PATH=mobiuslabsgmbh/faster-whisper-large-v3-turbo ./run.sh /tmp/live --transcripts asr --out /tmp/live-out";

export const DEMO_STEPS: DemoStep[] = [
  { href: "/overview", moment: "Start", title: "Every call, checked", say: "Every Swiss German call is checked, not a sample. This is today's result." },
  { href: `/calls/${DEMO_ALERT}/processing`, moment: "Moment 1", title: "From audio to alert (recorded replay)", say: "One call through every step, with what each step produced. Optional: the same pipeline live in the terminal.", live: LIVE_RUN },
  { href: `/calls/${DEMO_ALERT}`, moment: "Moment 1", title: "The alert and its evidence", say: "Reason, risk against the line, the passage, the facts behind it. Click a fact." },
  { href: "/settings/threshold?keyword_review=2", moment: "Moment 2", title: "One switch, visible effect", say: "Keyword review on: watch missed cases, false alarms and review load move, and the calls that go to Review. Nothing is saved." },
  { href: "/settings/keywords", moment: "Moment 2", title: "Keywords without code", say: "Add a word to a family: its hit count and the calls it changes appear at once." },
  { href: `/calls/${DEMO_HARMLESS}`, moment: "Moment 3", title: "A harmless call with keywords", say: "The same insider words as the alert, heard in six passages, but about public reports: No alert, with the judge's reason and what would change it." },
  { href: "/quality", moment: "Moment 4", title: "Detection quality", say: "The AI judge: no false alarm, recall said out loud, the ranges, and what we measured and changed." },
  { href: "/how-it-runs", moment: "Close", title: "How it runs", say: "Self-hosted end to end; no cloud AI." },
];

const KEY = "sentinel.demo.step";
/** Current step index, or null when demo mode is off. Session-scoped so a reload keeps the place. */
export function demoStep(): number | null {
  try { const v = sessionStorage.getItem(KEY); return v == null ? null : Math.max(0, Math.min(DEMO_STEPS.length - 1, Number(v))); } catch { return null; }
}
export function setDemoStep(i: number | null) {
  const prev = demoStep();
  try { if (i == null) sessionStorage.removeItem(KEY); else sessionStorage.setItem(KEY, String(i)); } catch { /* private window: demo bar still works for this page */ }
  // every real step change (→ / ←, a step dot, Esc, start) throws away unsaved settings drafts BEFORE the next page opens,
  // so step 4's "keyword review on" never leaks into steps 5–8: they always show the shipped settings
  if (prev !== i) window.dispatchEvent(new Event(DRAFT_RESET));
  window.dispatchEvent(new Event("sentinel-demo"));
}

const DRAFT_RESET = "sentinel-draft-reset";
/** Unsaved settings drafts call this to be discarded when the demo changes step. */
export function useDemoDraftReset(reset: () => void) {
  useEffect(() => {
    window.addEventListener(DRAFT_RESET, reset);
    return () => window.removeEventListener(DRAFT_RESET, reset);
  }, [reset]);
}

/** "Same sentence, two verdicts": two calls where a customer reads six digits aloud, in different situations (found by
 *  searching the transcripts; the case's own deep-dive pair). Override with NEXT_PUBLIC_SAME_SENTENCE="call_a,call_b". */
export const SAME_SENTENCE_PAIR: [string, string] = ((process.env.NEXT_PUBLIC_SAME_SENTENCE || "call_005,call_018").split(",").map((s) => s.trim()) as [string, string]);
