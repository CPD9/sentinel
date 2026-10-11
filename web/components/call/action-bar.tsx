"use client";
// Act on one call in one click (Nik's design 04: dismiss · flag · escalate · confirm fraud). Every button writes officer
// feedback; none changes the decision by itself (feedback feeds the suggested changes in Settings → Threshold).
//   dismiss        → false_alarm   (only when something was flagged)
//   flag           → missed        (only on Review / No alert: "this should have been an alert")
//   escalate       → escalate      (only when the API accepts it, GET /api/capabilities)
//   confirm fraud  → correct (+ report via the trigger API when the API exposes it)
import { Check } from "lucide-react";
import { useState } from "react";
import { ApiError, getCapabilities, getFeedback, isFixtures, postFeedback } from "@/lib/data";
import { VERDICT_LABEL, fmtDateTime } from "@/lib/format";
import type { Decision, Verdict } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const ACTIONS: { verdict: Verdict; label: string; writes: string; show: (d: Decision) => boolean; primary?: boolean }[] = [
  { verdict: "false_alarm", label: "dismiss", writes: "Records a false alarm.", show: (d) => d !== "no_alert" },
  { verdict: "missed", label: "flag", writes: "Records that this should have been an alert.", show: (d) => d !== "alarm" },
  { verdict: "escalate", label: "escalate", writes: "Sends the call to the review queue for a second person.", show: () => true },
  { verdict: "correct", label: "confirm fraud", writes: "Records the alert as correct.", show: (d) => d === "alarm", primary: true },
];

export function ActionBar({ callId, decision, compact }: { callId: string; decision: Decision; compact?: boolean }) {
  const all = useAsync(getFeedback, "feedback");
  const caps = useAsync(getCapabilities, "capabilities");
  const [pending, setPending] = useState<Verdict | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const mine = all.data?.find((e) => e.call_id === callId) ?? null;
  const shown = pending ?? mine?.verdict ?? null;
  const unavailable = all.status === "error" && all.error.notAvailable;
  const accepted = new Set(caps.data?.verdicts ?? []);
  const actions = ACTIONS.filter((a) => a.show(decision) && (a.verdict !== "escalate" || accepted.has("escalate")));

  const choose = async (v: Verdict) => {
    setErr(null); setPending(v);
    try { await postFeedback(callId, v); all.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setPending(null); }
  };

  return (
    <section aria-label="Act on this call" className="space-y-2">
      <div role="group" aria-label="Your verdict" className="grid gap-3" style={{ gridTemplateColumns: `repeat(${actions.length}, minmax(0, 1fr))` }}>
        {actions.map((a) => {
          const on = shown === a.verdict;
          return (
            <button key={a.verdict} type="button" aria-pressed={on} title={a.writes}
              disabled={pending != null || all.status === "loading" || unavailable} onClick={() => choose(a.verdict)}
              className={cn("inline-flex h-10 items-center justify-center gap-1.5 rounded-full border text-sm font-medium transition-colors duration-[var(--dur-fast)] disabled:cursor-not-allowed disabled:opacity-50",
                a.primary || on ? "border-primary bg-primary text-primary-foreground hover:opacity-90" : "border-foreground/60 hover:bg-muted")}>
              {on && <Check className="size-3.5" aria-hidden />}{a.label}
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {err ? <span role="alert" className="text-alarm">Could not save: {err}</span>
          : mine ? <>Recorded: <b>{VERDICT_LABEL[mine.verdict].toLowerCase()}</b>, {fmtDateTime(mine.ts)}. Click another button to change it.</>
          : unavailable ? "Recording a verdict is not available on this server yet."
          : compact ? "Your verdict feeds suggestions; it never changes the decision."
          : "Your verdict never changes the decision by itself; it feeds the suggested changes in Settings."}
        {decision === "alarm" && !caps.data?.report && !compact && " Report to the trigger API: not available yet."}
        {isFixtures && " (MOCK: kept in this browser only.)"}
      </p>
    </section>
  );
}
