"use client";
import { HelpCircle, ShieldQuestion } from "lucide-react";
import Link from "next/link";
import { CriterionChip } from "@/components/shell/badges";
import { ScoreBar } from "@/components/shell/score";
import { EmptyState } from "@/components/shell/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { criterionColor } from "@/lib/colors";
import { pct } from "@/lib/format";
import type { CallResult, DecisionTrace, Finding } from "@/lib/types";
import type { Loadable } from "@/lib/use-async";

export function SummaryTab({ result, trace }: { result: CallResult; trace: Loadable<DecisionTrace> }) {
  const th = trace.data?.thresholds;
  const sorted = [...result.findings].sort((a, b) => b.risk - a.risk);
  const flagged = th ? sorted.filter((f) => f.risk >= th.review) : sorted;
  const considered = th ? sorted.filter((f) => f.risk < th.review) : [];
  const markers = th ? [{ at: th.review, label: "review" }, { at: th.alarm, label: "alarm" }] : [];

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>Narrative</CardTitle></CardHeader>
          <CardContent className="pt-2">
            {result.narrative ? <p className="max-w-prose text-sm leading-relaxed">{result.narrative}</p> : <p className="text-sm text-muted-foreground">No narrative was written for this call.</p>}
          </CardContent>
        </Card>

        <div>
          <h2 className="mb-2 text-sm font-semibold">Findings</h2>
          {result.findings.length === 0 ? (
            <EmptyState>No compliance-relevant passages found.</EmptyState>
          ) : (
            <div className="space-y-2">
              {flagged.map((f, i) => <FindingRow key={`f${i}`} f={f} id={result.call_id} markers={markers} />)}
              {considered.length > 0 && (
                <>
                  <div className="flex items-center gap-3 pt-2 text-xs text-muted-foreground"><span className="h-px flex-1 bg-border" />considered, not flagged (risk below the review threshold {th ? pct(th.review) : ""})<span className="h-px flex-1 bg-border" /></div>
                  {considered.map((f, i) => <FindingRow key={`c${i}`} f={f} id={result.call_id} markers={markers} muted />)}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      <aside className="space-y-4">
        {trace.status === "error" && trace.error.status !== 404 && (
          <p className="rounded-md border border-border bg-muted p-3 text-xs text-muted-foreground">The decision trace could not be loaded, so the “why not flagged” and “what would change” boxes are missing. {trace.error.message}</p>
        )}
        {trace.data?.why_not_flagged && (
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldQuestion className="size-4" />Why not flagged</CardTitle></CardHeader>
            <CardContent className="pt-2 text-sm leading-relaxed">{trace.data.why_not_flagged}</CardContent></Card>
        )}
        {trace.data?.what_would_change && (
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><HelpCircle className="size-4" />What would change this</CardTitle></CardHeader>
            <CardContent className="pt-2 text-sm leading-relaxed">{trace.data.what_would_change}</CardContent></Card>
        )}
        {trace.status === "loading" && !trace.data && <div className="skeleton h-24" aria-busy="true" />}
      </aside>
    </div>
  );
}

function FindingRow({ f, id, markers, muted }: { f: Finding; id: string; markers: { at: number; label: string }[]; muted?: boolean }) {
  return (
    <Card className={muted ? "opacity-75" : ""}>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <CriterionChip criterion={f.criterion} />
          <div className="w-40"><ScoreBar value={f.risk} color={criterionColor(f.criterion)} markers={markers} label={`${f.criterion} risk`} /></div>
          <span className="tabular text-sm font-semibold">{pct(f.risk)}</span>
          <Link href={`/calls/${id}?tab=evidence`} className="ml-auto text-xs underline underline-offset-2">
            {f.evidence.length} evidence passage{f.evidence.length === 1 ? "" : "s"}
          </Link>
        </div>
        <p className="text-sm leading-relaxed">{f.reason}</p>
      </CardContent>
    </Card>
  );
}
