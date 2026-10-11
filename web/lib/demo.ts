// Demo mode for the jury: a keyboard-driven path (→ / ←) over the SAME real screens, hitting the four required moments
// in order. No separate pages and no staged data: each step is a real URL plus one line telling the presenter what to show.
// The call ids default to the reference run; set NEXT_PUBLIC_DEMO_ALERT / NEXT_PUBLIC_DEMO_HARMLESS for another run.
export const DEMO_ALERT = process.env.NEXT_PUBLIC_DEMO_ALERT || "call_015";
export const DEMO_HARMLESS = process.env.NEXT_PUBLIC_DEMO_HARMLESS || "call_026";

export interface DemoStep { href: string; moment: string; title: string; say: string }

export const DEMO_STEPS: DemoStep[] = [
  { href: "/overview", moment: "Start", title: "Every call, checked", say: "Every Swiss German call is checked, not a sample. This is today's result." },
  { href: `/calls/${DEMO_ALERT}/processing`, moment: "Moment 1", title: "From audio to alert", say: "One call through every step, with what each step produced." },
  { href: `/calls/${DEMO_ALERT}`, moment: "Moment 1", title: "The alert and its evidence", say: "Reason, risk against the line, the passage, the facts behind it. Click a fact." },
  { href: "/settings/threshold?draft_alarm=0.5", moment: "Moment 2", title: "One threshold, visible effect", say: "Cautious lowers the alert line: watch calls move from Review to Alert. Nothing is saved." },
  { href: "/settings/keywords", moment: "Moment 2", title: "Keywords without code", say: "Add a word to a family: its hit count and the calls it changes appear at once." },
  { href: `/calls/${DEMO_HARMLESS}`, moment: "Moment 3", title: "A harmless call with keywords", say: "Keywords were heard, no rule broke: No alert, with why not flagged and what would change it." },
  { href: "/quality", moment: "Moment 4", title: "Detection quality", say: "On calls it was never tuned on, with the likely ranges." },
  { href: "/how-it-runs", moment: "Close", title: "How it runs", say: "Self-hosted end to end; no cloud AI." },
];

const KEY = "sentinel.demo.step";
/** Current step index, or null when demo mode is off. Session-scoped so a reload keeps the place. */
export function demoStep(): number | null {
  try { const v = sessionStorage.getItem(KEY); return v == null ? null : Math.max(0, Math.min(DEMO_STEPS.length - 1, Number(v))); } catch { return null; }
}
export function setDemoStep(i: number | null) {
  try { if (i == null) sessionStorage.removeItem(KEY); else sessionStorage.setItem(KEY, String(i)); } catch { /* private window: demo bar still works for this page */ }
  window.dispatchEvent(new Event("sentinel-demo"));
}
