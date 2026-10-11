"use client";
// Right panel of the inbox (Nik's design 04): the shared call top block (components/call/call-summary.tsx), so the
// panel and the full call page always show the decision, its reason and the passage player in the same place.
// Data: GET /calls/{id}, /trace, /analysis, /transcript. Trace, analysis and transcript may be missing (404): their
// parts then say "not available" instead of breaking.
import { RefreshCw } from "lucide-react";
import { CallHeader, CallSummary } from "@/components/call/call-summary";
import { Skeleton } from "@/components/ui/skeleton";
import { getAnalysis, getCall, getTrace, getTranscript } from "@/lib/data";
import type { AnalysisArtifact, CallListItem, CallResult, DecisionTrace, Thresholds, Transcript } from "@/lib/types";
import { useAsync } from "@/lib/use-async";

export function CallPanel({ item, thresholds }: { item: CallListItem; thresholds: Thresholds | null }) {
  const id = item.call_id;
  const version = item.updated_at ?? "";                    // a re-run (new updated_at) reloads the panel
  const pending = item.status === "queued" || item.status === "processing";
  const detail = useAsync(() => (pending ? Promise.resolve(null) : getCall(id)), `panel:${id}:${version}:${pending}`);
  const trace = useAsync<DecisionTrace | null>(() => (pending ? Promise.resolve(null) : getTrace(id)), `panel-trace:${id}:${version}`);
  const analysis = useAsync<AnalysisArtifact | null>(() => (pending ? Promise.resolve(null) : getAnalysis(id)), `panel-an:${id}:${version}`);
  const transcript = useAsync<Transcript | null>(() => (pending ? Promise.resolve(null) : getTranscript(id)), `panel-tr:${id}:${version}`);
  const result: CallResult | null = detail.data?.kind === "result" ? detail.data.data : null;
  const href = pending ? `/calls/${id}/processing` : `/calls/${id}`;

  return (
    <article aria-label={`Call ${id}`} className="elevated rounded-[var(--radius-panel)]">
      <CallHeader meta={item} decision={item.decision} href={href} pending={pending} />
      {pending ? (
        <p className="px-6 py-5 text-sm text-muted-foreground">Still being transcribed and checked. The decision appears here by itself when it is done.</p>
      ) : detail.status === "loading" && !detail.data ? (
        <div className="space-y-3 px-6 py-5" aria-busy="true"><Skeleton className="h-24" /><Skeleton className="h-12" /><Skeleton className="h-32" /></div>
      ) : detail.status === "error" && !detail.data ? (
        <p role="alert" className="flex flex-wrap items-center gap-2 px-6 py-5 text-sm text-muted-foreground">
          The details of this call could not be loaded ({detail.error.message}).
          <button type="button" onClick={detail.reload} className="inline-flex items-center gap-1 underline-offset-2 hover:underline"><RefreshCw className="size-3" aria-hidden />Retry</button>
        </p>
      ) : result ? (
        <CallSummary meta={item} result={result} trace={trace} analysis={analysis} transcript={transcript} thresholds={thresholds} compact />
      ) : null}
    </article>
  );
}
