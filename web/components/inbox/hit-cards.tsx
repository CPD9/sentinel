"use client";
// "Needs attention": one card per alarm / review call (slide "3 · The brief": list of hits, listen to the passage, with the reason).
// Every card uses the same three columns: the verdict | why (reason + passage + player) | risk, confidence and the action.
// The list row gives decision, criteria, risk and confidence; each card loads its call's result for the reason and the first
// quote, and a review card without a stage error also loads the trace to say why the system is unsure.
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { DecisionBadge, StageErrorChip } from "@/components/shell/badges";
import { ConfidenceGauge, RiskGauge } from "@/components/shell/gauge";
import { EmptyState } from "@/components/shell/states";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";
import { PassagePlayer } from "@/components/call/passage-player";
import { CRITERION_LABEL, SPEAKER_COLOR, criterionColor } from "@/lib/colors";
import { getCall, getTrace } from "@/lib/data";
import { fmtTime } from "@/lib/format";
import type { CallListItem, CallResult, Criterion, DecisionPath, DecisionTrace, Thresholds } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const RANK: Record<string, number> = { alarm: 0, review: 1 };

/** Why a call went to review, in plain words (decide.py priority order, CLAUDE.md step 8). */
const WHY_REVIEW: Partial<Record<DecisionPath, string>> = {
  stage_error: "A processing step failed, so the call was not fully analysed.",
  missing_evidence: "Some cited evidence could not be verified against the transcript.",
  contradictory_evidence: "The evidence points both ways.",
  low_confidence: "Confidence is below the gate, for example because of unclear audio or transcript.",
  review_band: "The risk sits between the review and the alarm threshold.",
};

const duration = (s: number | null) => (s == null ? "–" : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

export function HitList({ calls, thresholds }: { calls: CallListItem[] | null; thresholds?: Thresholds | null }) {
  const [only, setOnly] = useState<Criterion | "">("");
  const flagged = useMemo(() => (calls ?? [])
    .filter((c) => (c.status === "done" || c.status === "error") && (c.decision === "alarm" || c.decision === "review"))
    .sort((a, b) => RANK[a.decision!] - RANK[b.decision!] || (b.risk_score ?? 0) - (a.risk_score ?? 0)), [calls]);
  const criteria = useMemo(() => [...new Set(flagged.flatMap((c) => c.criteria))], [flagged]);
  const shown = only ? flagged.filter((c) => c.criteria.includes(only)) : flagged;

  return (
    <section aria-labelledby="attention" className="space-y-4">
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
        <div className="space-y-3" aria-busy="true">{[0, 1].map((i) => <Skeleton key={i} className="h-44 rounded-2xl" />)}</div>
      ) : flagged.length === 0 ? (
        <EmptyState>Nothing needs your attention. Every checked call came out as no alert; you find them under “All calls”.</EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState>No flagged call of this kind. Choose “All” to see every hit.</EmptyState>
      ) : (
        <div className="space-y-3">{shown.map((c, i) => <HitCard key={c.call_id} item={c} thresholds={thresholds} index={i} />)}</div>
      )}
    </section>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick}
      className={cn("inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
        active ? "border-primary bg-primary/15 font-semibold text-link" : "border-border text-muted-foreground hover:bg-muted hover:text-foreground")}>
      {children}
    </button>
  );
}

function HitCard({ item, thresholds, index }: { item: CallListItem; thresholds?: Thresholds | null; index: number }) {
  const id = item.call_id;
  const version = item.updated_at ?? "";                       // a re-run (new updated_at) reloads the card
  const detail = useAsync(() => getCall(id), `hit:${id}:${version}`);
  const askTrace = item.decision === "review" && item.n_stage_errors === 0;
  const trace = useAsync<DecisionTrace | null>(() => (askTrace ? getTrace(id) : Promise.resolve(null)), `hit-trace:${id}:${version}:${askTrace}`);
  const result: CallResult | null = detail.data?.kind === "result" ? detail.data.data : null;

  const findings = result ? [...result.findings].sort((a, b) => b.risk - a.risk) : [];
  const top = findings[0] ?? null;
  const ev = top?.evidence[0] ?? null;
  const passages = findings.reduce((n, f) => n + f.evidence.length, 0);
  const alarm = item.decision === "alarm";
  const criterion = top?.criterion ?? item.criteria[0] ?? null;

  const whyReview = result && result.stage_errors.length > 0
    ? `${WHY_REVIEW.stage_error} ${result.stage_errors.map((e) => `${e.stage}: ${e.message}`).join("; ")}`
    : trace.data ? `${WHY_REVIEW[trace.data.decision_path] ?? "The system is not sure enough to decide alone."}${trace.data.what_would_change ? ` ${trace.data.what_would_change}` : ""}`
    : trace.status === "loading" ? null : "The system is not sure enough to decide alone.";

  return (
    <article className="hit-card relative overflow-hidden rounded-2xl border border-border bg-card" style={{ animationDelay: `${index * 70}ms` }}>
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", alarm ? "bg-alarm" : "bg-review")} />
      <div className="grid gap-5 py-5 pl-6 pr-5 md:grid-cols-[10.5rem_minmax(0,1fr)_13rem]">

        {/* 1 · the verdict */}
        <div className="flex flex-wrap items-start gap-x-3 gap-y-2 md:flex-col">
          <span className="flex items-center gap-1"><DecisionBadge decision={item.decision} /><InfoTip term={alarm ? "alarm" : "review"} /></span>
          {criterion && (
            <span className="flex items-center gap-2 text-sm font-medium">
              <span aria-hidden className="inline-block size-2 shrink-0 rounded-full" style={{ background: criterionColor(criterion) }} />
              {CRITERION_LABEL[criterion as Criterion] ?? criterion}
            </span>
          )}
          <StageErrorChip count={item.n_stage_errors} />
          <p className="text-xs leading-relaxed text-muted-foreground md:mt-auto">{id}<br />{duration(item.duration_s)}</p>
        </div>

        {/* 2 · why */}
        <div className="min-w-0 space-y-3">
          {detail.status === "loading" && !detail.data ? (
            <div className="space-y-2" aria-busy="true"><Skeleton className="h-5 w-3/4" /><Skeleton className="h-16 w-full rounded-xl" /></div>
          ) : detail.status === "error" && !detail.data ? (
            <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              The details of this call could not be loaded ({detail.error.message}).
              <button type="button" onClick={detail.reload} className="inline-flex items-center gap-1 text-link underline-offset-2 hover:underline"><RefreshCw className="size-3" aria-hidden />Retry</button>
            </p>
          ) : (
            <>
              {top && !(result && result.stage_errors.length > 0) && <p className="text-[15px] font-medium leading-snug">{top.reason}</p>}
              {!alarm && (
                <div className="rounded-xl border border-review/40 bg-review-bg/60 px-3.5 py-2.5 text-sm">
                  <p className="font-medium text-review">Why a person must look</p>
                  <p className="mt-0.5 leading-relaxed">{whyReview ?? "…"}</p>
                </div>
              )}
              {ev && (
                <div className="space-y-2.5 rounded-xl bg-muted/50 p-3.5">
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium" style={{ color: SPEAKER_COLOR[ev.speaker] }}>{ev.speaker === "unknown" ? "Unknown speaker" : ev.speaker === "advisor" ? "Advisor" : "Customer"}</span>
                    {ev.start_s != null ? `, ${fmtTime(ev.start_s)}` : ", no timestamp (reference transcript)"}
                  </p>
                  <blockquote lang="gsw" className="text-sm leading-relaxed">“{ev.text}”</blockquote>
                  {ev.start_s != null && ev.end_s != null && <PassagePlayer callId={id} path={ev.snippet_path} start={ev.start_s} end={ev.end_s} mock={item.is_mock} />}
                </div>
              )}
              {findings.length > 0 && (
                <p className="text-xs text-muted-foreground">{plural(findings.length, "finding")}, {plural(passages, "evidence passage")}</p>
              )}
            </>
          )}
        </div>

        {/* 3 · the numbers and the action */}
        <div className="flex flex-col gap-4 md:border-l md:border-border md:pl-5">
          <RiskGauge value={item.risk_score} review={thresholds?.review} alarm={thresholds?.alarm} />
          <ConfidenceGauge value={item.confidence} gate={thresholds?.confidence_gate} />
          <Link href={`/calls/${id}`}
            className="mt-auto inline-flex h-10 items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90">
            Review call
          </Link>
        </div>
      </div>
    </article>
  );
}
