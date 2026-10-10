"use client";
import { Check, Flag, ThumbsUp, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiError, getFeedback, isFixtures, postFeedback } from "@/lib/data";
import { VERDICT_LABEL, fmtDateTime } from "@/lib/format";
import type { Decision, Verdict } from "@/lib/types";
import { VERDICTS, verdictAllowed } from "@/lib/types";
import { useAsync } from "@/lib/use-async";

const ICON = { false_alarm: Flag, missed: TriangleAlert, correct: ThumbsUp } as const;
const WHY_NOT: Record<Verdict, string> = {
  false_alarm: "Nothing was flagged, so there is no false alarm to report.",
  missed: "This is already an alarm, so nothing was missed.",
  correct: "",
};

/** Officer verdict on this call. It never changes the decision; it feeds the suggested changes in Settings. */
export function FeedbackBar({ callId, decision }: { callId: string; decision: Decision }) {
  const all = useAsync(getFeedback, "feedback");
  const [pending, setPending] = useState<Verdict | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const mine = all.data?.find((e) => e.call_id === callId) ?? null;
  const shown = pending ?? mine?.verdict ?? null;
  const unavailable = all.status === "error" && all.error.notAvailable;       // the server has no feedback route yet

  const choose = async (v: Verdict) => {
    setErr(null); setPending(v); setBusy(true);
    try {
      await postFeedback(callId, v, note.trim() || undefined);
      all.reload();
      setNote("");
    } catch (e) {
      setErr(e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : e.message) : String(e));
    } finally { setPending(null); setBusy(false); }      // on failure this rolls back to the stored verdict
  };

  return (
    <section aria-label="Your verdict on this call" className="rounded-md border border-border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Was this decision right?</span>
        <div role="group" aria-label="Verdict" className="flex flex-wrap gap-1.5">
          {VERDICTS.map((v) => {
            const Icon = ICON[v];
            const ok = verdictAllowed(v, decision);
            const on = shown === v;
            return (
              <Button key={v} size="sm" variant={on ? "default" : "outline"} aria-pressed={on} disabled={busy || all.status === "loading" || unavailable || !ok}
                title={ok ? undefined : WHY_NOT[v]} onClick={() => choose(v)}>
                {on && !busy ? <Check className="size-3.5" aria-hidden /> : <Icon className="size-3.5" aria-hidden />}{VERDICT_LABEL[v]}
              </Button>
            );
          })}
        </div>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Optional note, sent with your next click"
          aria-label="Optional note for the verdict" className="h-8 min-w-48 flex-1 rounded-md border border-border bg-card px-2 text-sm" />
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground" aria-live="polite">
        {err ? <span role="alert" className="text-alarm">Could not save your verdict: {err}</span>
          : mine ? <>You marked this <b>{VERDICT_LABEL[mine.verdict].toLowerCase()}</b> on {fmtDateTime(mine.ts)}{mine.note && <> — “{mine.note}”</>}. Click another button to change it.</>
          : unavailable ? "Officer feedback is not available on this server yet."
          : all.status === "error" ? "Your earlier verdicts could not be loaded; you can still add one."
          : "No verdict yet. Your verdicts feed the suggested changes in Settings; they never change a decision by themselves."}
        {isFixtures && " (MOCK: kept in this browser only.)"}
      </p>
    </section>
  );
}
