"use client";
// Act on one call in one click (Nik's design 04). Every button writes officer feedback (docs/API.md POST /feedback);
// none changes the decision by itself (feedback feeds the suggested changes in Settings → Threshold).
//   dismiss        → false_alarm                                      (Alert, Review)
//   flag           → missed: "this should have been flagged"          (No alert)
//   escalate       → escalate: a person above me must look            (always)
//   confirm fraud  → correct on an Alert, missed on a Review, then POST /calls/{id}/report (trigger API, dry-run
//                    unless the server sends for real; the result says which)
import { Check } from "lucide-react";
import { useState } from "react";
import { ApiError, getFeedback, isFixtures, isLocalRun, postFeedback, reportCall } from "@/lib/data";
import { VERDICT_LABEL, fmtDateTime } from "@/lib/format";
import type { Decision, Verdict } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

type Action = { key: string; verdict: Verdict; label: string; writes: string; report?: boolean; primary?: boolean };

function actionsFor(d: Decision): Action[] {
  const escalate: Action = { key: "escalate", verdict: "escalate", label: "escalate", writes: "Sends the call to a second person; the decision stays as it is." };
  if (d === "no_alert") return [
    { key: "flag", verdict: "missed", label: "flag", writes: "Records that this call should have been flagged." },
    escalate,
  ];
  return [
    { key: "dismiss", verdict: "false_alarm", label: "dismiss", writes: "Records a false alarm." },
    escalate,
    { key: "confirm", verdict: d === "alarm" ? "correct" : "missed", label: "confirm fraud", report: true, primary: true,
      writes: d === "alarm" ? "Records the alert as correct and reports it to the trigger API." : "Records that this should have been an alert and reports it to the trigger API." },
  ];
}

export function ActionBar({ callId, decision, compact }: { callId: string; decision: Decision; compact?: boolean }) {
  const all = useAsync(getFeedback, "feedback");
  const [pending, setPending] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reported, setReported] = useState<string | null>(null);
  const mine = all.data?.find((e) => e.call_id === callId) ?? null;
  const unavailable = all.status === "error" && all.error.notAvailable;
  const actions = actionsFor(decision);
  const active = pending ?? chosen ?? actions.find((a) => a.verdict === mine?.verdict)?.key ?? null;

  const choose = async (a: Action) => {
    setErr(null); setReported(null); setPending(a.key);
    try {
      await postFeedback(callId, a.verdict);
      setChosen(a.key);
      all.reload();
      if (a.report) {
        try {
          const r = await reportCall(callId);
          setReported(r.errors.length ? `Report failed: ${r.errors.join("; ")}` : `${r.records.length} report${r.records.length === 1 ? "" : "s"} ${r.dry_run ? "prepared (dry run, nothing sent)" : "sent to the trigger API"}.`);
        } catch (e) { setReported(e instanceof ApiError ? e.message : String(e)); }
      }
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setPending(null); }
  };

  return (
    <section aria-label="Act on this call" className="space-y-2">
      <div role="group" aria-label="Your verdict" className="grid gap-3" style={{ gridTemplateColumns: `repeat(${actions.length}, minmax(0, 1fr))` }}>
        {actions.map((a) => {
          const on = active === a.key;
          return (
            <button key={a.key} type="button" aria-pressed={on} title={a.writes}
              disabled={pending != null || all.status === "loading" || unavailable} onClick={() => choose(a)}
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
        {reported && <> {reported}</>}
        {isFixtures && " (MOCK: kept in this browser only.)"}
        {isLocalRun && " (Local run: kept in this server’s memory until it restarts.)"}
      </p>
    </section>
  );
}
