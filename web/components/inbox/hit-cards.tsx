"use client";
// "Needs attention": one card per alarm / review call (slide "3 · The brief": list of hits, listen to the passage, with the reason).
// The list row gives decision, criteria, risk and confidence; each card loads its call's result for the reason and the first quote,
// and a review card without a stage error also loads the trace to say why the system is unsure.
import { ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { CriterionChip, DecisionBadge, SpeakerChip, StageErrorChip } from "@/components/shell/badges";
import { RiskConfidence } from "@/components/shell/score";
import { EmptyState } from "@/components/shell/states";
import { Skeleton } from "@/components/ui/skeleton";
import { SnippetPlayer } from "@/components/call/snippet-player";
import { CRITERION_LABEL, criterionColor } from "@/lib/colors";
import { getCall, getTrace } from "@/lib/data";
import { fmtRange, fmtTime } from "@/lib/format";
import type { CallListItem, CallResult, Criterion, DecisionPath, DecisionTrace } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const RANK: Record<string, number> = { alarm: 0, review: 1 };

/** Why a call went to review, in plain words (decide.py priority order, CLAUDE.md step 8). */
const WHY_REVIEW: Partial<Record<DecisionPath, string>> = {
  stage_error: "A processing step failed, so the call was not fully analysed.",
  missing_evidence: "Some cited evidence could not be verified against the transcript.",
  contradictory_evidence: "The evidence points both ways.",
  low_confidence: "Confidence is below the gate (e.g. unclear audio or transcript).",
  review_band: "The risk sits between the review and the alarm threshold.",
};

export function HitList({ calls, gate }: { calls: CallListItem[] | null; gate?: number }) {
  const [only, setOnly] = useState<Criterion | "">("");
  const flagged = useMemo(() => (calls ?? [])
    .filter((c) => (c.status === "done" || c.status === "error") && (c.decision === "alarm" || c.decision === "review"))
    .sort((a, b) => RANK[a.decision!] - RANK[b.decision!] || (b.risk_score ?? 0) - (a.risk_score ?? 0)), [calls]);
  const criteria = useMemo(() => [...new Set(flagged.flatMap((c) => c.criteria))], [flagged]);
  const shown = only ? flagged.filter((c) => c.criteria.includes(only)) : flagged;

  return (
    <section aria-labelledby="attention" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="attention" className="text-lg font-semibold tracking-tight">Needs attention</h2>
        {criteria.length > 0 && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by kind of fraud">
            <Chip active={!only} onClick={() => setOnly("")}>All</Chip>
            {criteria.map((c) => (
              <Chip key={c} active={only === c} onClick={() => setOnly(only === c ? "" : c)}>
                <span aria-hidden className="inline-block size-2 rounded-full" style={{ background: criterionColor(c) }} />{CRITERION_LABEL[c] ?? c}
              </Chip>
            ))}
          </div>
        )}
      </div>

      {!calls ? (
        <div className="space-y-3" aria-busy="true">{[0, 1].map((i) => <Skeleton key={i} className="h-40 rounded-2xl" />)}</div>
      ) : flagged.length === 0 ? (
        <EmptyState>Nothing needs your attention. Every checked call came out as no alert; you find them under “All calls”.</EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState>No flagged call of this kind. Choose “All” to see every hit.</EmptyState>
      ) : (
        <div className="space-y-3">{shown.map((c) => <HitCard key={c.call_id} item={c} gate={gate} />)}</div>
      )}
    </section>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick}
      className={cn("inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs",
        active ? "border-primary bg-primary/15 font-semibold text-link" : "border-border text-muted-foreground hover:bg-muted hover:text-foreground")}>
      {children}
    </button>
  );
}

function HitCard({ item, gate }: { item: CallListItem; gate?: number }) {
  const id = item.call_id;
  const version = item.updated_at ?? "";                       // a re-run (new updated_at) reloads the card
  const detail = useAsync(() => getCall(id), `hit:${id}:${version}`);
  const askTrace = item.decision === "review" && item.n_stage_errors === 0;
  const trace = useAsync<DecisionTrace | null>(() => (askTrace ? getTrace(id) : Promise.resolve(null)), `hit-trace:${id}:${version}:${askTrace}`);
  const result: CallResult | null = detail.data?.kind === "result" ? detail.data.data : null;

  const findings = result ? [...result.findings].sort((a, b) => b.risk - a.risk) : [];
  const top = findings[0] ?? null;
  const ev = top?.evidence[0] ?? null;
  const alarm = item.decision === "alarm";

  return (
    <article className="relative overflow-hidden rounded-2xl border border-border bg-card">
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", alarm ? "bg-alarm" : "bg-review")} />
      <div className="space-y-3 py-4 pl-6 pr-5">
        <header className="flex flex-wrap items-center gap-2">
          <DecisionBadge decision={item.decision} size="sm" />
          {top ? <CriterionChip criterion={top.criterion} /> : item.criteria[0] ? <CriterionChip criterion={item.criteria[0]} /> : null}
          <StageErrorChip count={item.n_stage_errors} />
          <span className="ml-auto font-mono text-xs text-muted-foreground">{id} · {fmtTime(item.duration_s)}</span>
        </header>

        {detail.status === "loading" && !detail.data ? (
          <div className="space-y-2" aria-busy="true"><Skeleton className="h-5 w-3/4" /><Skeleton className="h-4 w-1/2" /></div>
        ) : detail.status === "error" && !detail.data ? (
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            Details could not be loaded ({detail.error.message}).
            <button type="button" onClick={detail.reload} className="inline-flex items-center gap-1 text-link underline-offset-2 hover:underline"><RefreshCw className="size-3" />Retry</button>
          </p>
        ) : (
          <>
            {result && result.stage_errors.length > 0 ? (
              <>
                <p className="text-base font-medium leading-snug">Not fully analysed, so a person has to check this call.</p>
                <p className="text-sm text-muted-foreground"><span className="font-medium text-foreground">Why review: </span>
                  {result.stage_errors.map((e) => `${e.stage} failed (${e.message})`).join("; ")}</p>
              </>
            ) : (
              <>
                {top && <p className="text-base font-medium leading-snug">{top.reason}</p>}
                {!alarm && (
                  <p className="text-sm text-muted-foreground"><span className="font-medium text-foreground">Why review: </span>
                    {trace.data ? (WHY_REVIEW[trace.data.decision_path] ?? "The system is not sure enough to decide alone.") : trace.status === "loading" ? "…" : "The system is not sure enough to decide alone."}
                    {trace.data?.what_would_change && <> {trace.data.what_would_change}</>}
                  </p>
                )}
              </>
            )}

            {ev && (
              <div className="space-y-2 rounded-xl bg-muted/50 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <SpeakerChip speaker={ev.speaker} />
                  <span className="tabular">{ev.start_s != null ? fmtRange(ev.start_s, ev.end_s) : "no timestamp (reference transcript)"}</span>
                  {top && top.evidence.length > 1 && <span>· +{top.evidence.length - 1} more passage{top.evidence.length > 2 ? "s" : ""}</span>}
                </div>
                <blockquote lang="gsw" className="text-sm leading-relaxed">“{ev.text}”</blockquote>
                {ev.start_s != null && ev.end_s != null && <SnippetPlayer callId={id} path={ev.snippet_path} start={ev.start_s} end={ev.end_s} waveform={null} />}
              </div>
            )}
          </>
        )}

        <footer className="flex flex-wrap items-center gap-3">
          <RiskConfidence risk={item.risk_score} confidence={item.confidence} gate={gate} compact />
          {findings.length > 1 && <span className="text-xs text-muted-foreground">+{findings.length - 1} more finding{findings.length > 2 ? "s" : ""}</span>}
          <Link href={`/calls/${id}`} className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-link underline-offset-2 hover:underline">
            Open call <ArrowRight className="size-3.5" />
          </Link>
        </footer>
      </div>
    </article>
  );
}
