"use client";
import { ArrowRight, Eye, Lightbulb } from "lucide-react";
import { useState } from "react";
import { DecisionBadge } from "@/components/shell/badges";
import { EmptyState, ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, applySuggestion, getSuggestions, isFixtures } from "@/lib/data";
import { componentLabel } from "@/lib/format";
import type { Patch, Suggestion } from "@/lib/types";
import { patchComponents, samePatch } from "@/lib/whatif-mock";
import { useAsync } from "@/lib/use-async";
import { ConfirmDialog } from "./confirm-dialog";

const errText = (e: unknown) => (e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : `${e.code}: ${e.detail}`) : String(e));

/** Ranked, simulated config changes built from the officer's verdicts. Preview loads one into the draft; Apply asks for confirmation. */
export function SuggestionsCard({ activePatch, onPreview, onApplied }: { activePatch: Patch | null; onPreview: (p: Patch) => void; onApplied: (message: string) => void }) {
  const state = useAsync(() => getSuggestions(), "suggestions");
  const [confirm, setConfirm] = useState<Suggestion | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const apply = async () => {
    if (!confirm) return;
    setBusy(true); setErr(null);
    try {
      const r = await applySuggestion(confirm.id, note.trim() || undefined);
      const message = `Applied: ${confirm.title}. Re-running ${r.rerun.stages.join(" → ")} for ${r.rerun.n_calls} calls from cache; recorded in the audit log.`;
      setConfirm(null); setNote("");
      onApplied(message);          // the parent shows it and refreshes this card; it must outlive this component's remount
    } catch (e) {
      setErr(errText(e));
      if (e instanceof ApiError && e.status === 409) state.reload();     // config moved since the suggestion was made
    } finally { setBusy(false); }
  };

  const d = state.data;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2"><Lightbulb className="size-4" aria-hidden />Suggested changes</CardTitle>
          <CardDescription>
            {d ? <>Built from your {d.n_feedback} verdict{d.n_feedback === 1 ? "" : "s"} ({d.counts_by_verdict.false_alarm} false alarm, {d.counts_by_verdict.missed} missed, {d.counts_by_verdict.correct} correct). Never applied automatically.</> : "Built from your false alarm / missed / correct verdicts. Never applied automatically."}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isFixtures && <p role="note" className="rounded-md border border-review bg-review-bg px-3 py-2 text-xs text-review">MOCK: sample suggestions computed by the real search over 12 invented calls. They are not recomputed from your clicks, and Apply is disabled.</p>}
        {state.status === "loading" && !d ? <SkeletonBlock rows={4} />
          : state.status === "error" && !d && state.error.notAvailable ? <EmptyState>{state.error.message} The settings below still work.</EmptyState>
          : state.status === "error" && !d ? <ErrorCard error={state.error} onRetry={state.reload} title="Could not load suggestions" />
          : d && d.suggestions.length === 0 ? (
            <EmptyState>{d.reason ?? "No suggestions."} {d.n_feedback === 0 && "Open a call and use the False alarm / Missed / Correct buttons."}</EmptyState>
          ) : d && (
            <>
              <ol className="space-y-3">{d.suggestions.map((s, i) => {
                const active = !!activePatch && samePatch(activePatch, s.patch);
                const e = s.effect;
                return (
                  <li key={s.id} className={`rounded-md border p-3 ${active ? "border-foreground" : "border-border"}`}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="font-medium"><span className="mr-2 text-muted-foreground">#{i + 1}</span>{s.title}</p>
                      <div className="flex gap-2">
                        <Button size="sm" variant={active ? "default" : "outline"} onClick={() => onPreview(s.patch)} aria-pressed={active}><Eye className="size-3.5" />{active ? "Previewing" : "Preview"}</Button>
                        <Button size="sm" variant="outline" disabled={isFixtures} title={isFixtures ? "Disabled in fixtures mode (MOCK)" : undefined} onClick={() => { setErr(null); setConfirm(s); }}>Apply…</Button>
                      </div>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{s.rationale}</p>
                    <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                      <div><dt className="inline text-muted-foreground">Fixes (arrow = only partly) </dt><dd className="inline">{s.fixed.length ? s.fixed.map((c) => {
                        const f = e.flipped.find((x) => x.call_id === c);
                        const partly = !!f && ((f.feedback_verdict === "false_alarm" && f.after !== "no_alert") || (f.feedback_verdict === "missed" && f.after !== "alarm"));
                        return <Badge key={c} className="mr-1 border-ok text-ok" title={partly ? `Only partly fixed: becomes ${f!.after}` : "Fixed"}>{c.replace(/^call_(MOCK_)?/, "#")}{partly && ` → ${f!.after}`}</Badge>;
                      }) : "none"}</dd></div>
                      <div><dt className="inline text-muted-foreground">Still wrong </dt><dd className="inline">{s.not_fixed.length ? s.not_fixed.map((c) => <Badge key={c} className="mr-1 border-review text-review">{c.replace(/^call_(MOCK_)?/, "#")}</Badge>) : "none"}</dd></div>
                      <div><dt className="inline text-muted-foreground">Other calls that change </dt><dd className="inline tabular">{s.collateral_flips.length}</dd></div>
                      <div><dt className="inline text-muted-foreground">Workload </dt><dd className="inline tabular">{e.workload.before.flagged_per_100.toFixed(1)} <ArrowRight className="inline size-3" aria-label="to" /> {e.workload.after.flagged_per_100.toFixed(1)} per 100</dd></div>
                    </dl>
                    <p className="mt-1 text-[11px] text-muted-foreground">Changes: {patchComponents(s.patch).map(componentLabel).join(" · ")}</p>
                  </li>
                );
              })}</ol>
              <p className="text-[11px] text-muted-foreground">{d.caveat}</p>
            </>
          )}
      </CardContent>

      <ConfirmDialog open={!!confirm} title="Apply this change?" confirmLabel="Apply change" busy={busy} error={err} onConfirm={apply} onClose={() => { if (!busy) { setConfirm(null); setErr(null); } }}>
        {confirm && (
          <div className="space-y-3 text-sm">
            <p className="font-medium">{confirm.title}</p>
            <ul className="list-disc pl-5 text-muted-foreground">{patchComponents(confirm.patch).map((c) => <li key={c}>{componentLabel(c)}</li>)}</ul>
            <p>This saves the configuration and re-runs the cheap stages from cache for every call. <b>{confirm.effect.flipped.length}</b> call{confirm.effect.flipped.length === 1 ? "" : "s"} would change decision:</p>
            <ul className="max-h-40 space-y-1 overflow-auto">{confirm.effect.flipped.map((f) => (
              <li key={f.call_id} className="flex items-center gap-2"><span className="font-mono text-xs">{f.call_id}</span><DecisionBadge decision={f.before} size="sm" /><ArrowRight className="size-3" aria-hidden /><DecisionBadge decision={f.after} size="sm" /></li>
            ))}</ul>
            <label className="block text-xs text-muted-foreground">Note for the audit log (optional)
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} className="mt-1 h-8 w-full rounded-md border border-border bg-card px-2 text-sm text-foreground" /></label>
            <p className="text-[11px] text-muted-foreground">Written to the audit log with the old and new configuration version. You can undo it by saving the previous values in Settings.</p>
          </div>
        )}
      </ConfirmDialog>
    </Card>
  );
}
