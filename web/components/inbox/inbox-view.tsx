"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Select } from "@/components/ui/select";
import { CriterionChip, DecisionBadge, StageErrorChip, StatusPill } from "@/components/shell/badges";
import { EmptyState, ErrorCard } from "@/components/shell/states";
import { ScoreBar } from "@/components/shell/score";
import { UploadZone } from "./upload";
import { getCalls, getThresholds, subscribeGlobalEvents } from "@/lib/data";
import { fmtDateTime, fmtTime } from "@/lib/format";
import { useReportMock } from "@/lib/mock-store";
import type { CallListItem, Criterion, Decision } from "@/lib/types";
import { CRITERIA, VARIANTS } from "@/lib/types";
import { useAsync } from "@/lib/use-async";

const DECISION_RANK: Record<string, number> = { alarm: 0, review: 1, no_alert: 2 };
const decisionRank = (d: Decision | null) => (d == null ? -1 : DECISION_RANK[d]);

type Sort = "default" | "risk" | "confidence" | "updated";

function sortRows(rows: CallListItem[], sort: Sort): CallListItem[] {
  const by = (f: (r: CallListItem) => number) => (a: CallListItem, b: CallListItem) => f(b) - f(a);
  const risk = (r: CallListItem) => r.risk_score ?? -1;
  const out = [...rows];
  if (sort === "risk") return out.sort(by(risk));
  if (sort === "confidence") return out.sort(by((r) => r.confidence ?? -1));
  if (sort === "updated") return out.sort(by((r) => Date.parse(r.updated_at ?? "") || 0));
  // default: alarm, review, no_alert; within each, risk descending. Queued/processing rows go first.
  return out.sort((a, b) => decisionRank(a.decision) - decisionRank(b.decision) || risk(b) - risk(a));
}

export function InboxView() {
  const calls = useAsync(getCalls, "calls");
  const gate = useAsync(() => getThresholds().then((t) => t.confidence_gate), "gate");
  const [decision, setDecision] = useState("");
  const [status, setStatus] = useState("");
  const [criterion, setCriterion] = useState("");
  const [variant, setVariant] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [sort, setSort] = useState<Sort>("default");
  const [stages, setStages] = useState<Record<string, string>>({});

  useReportMock("inbox", calls.data?.some((c) => c.is_mock) ? { is_mock: true } : null);

  // Global SSE: track the current stage per call; re-fetch the list on job_finished.
  useEffect(() => {
    const sub = subscribeGlobalEvents(
      (e) => {
        if (e.stage) setStages((s) => ({ ...s, [e.call_id]: e.stage! }));
        if (e.event === "job_finished" || e.event === "job_queued") calls.reload();
      },
      () => {},
    );
    return () => sub.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = useMemo(() => {
    const all = calls.data ?? [];
    return sortRows(
      all.filter((r) =>
        (!decision || r.decision === decision) && (!status || r.status === status) &&
        (!criterion || r.criteria.includes(criterion as Criterion)) && (!variant || r.variant === variant) &&
        (!onlyErrors || r.n_stage_errors > 0)),
      sort,
    );
  }, [calls.data, decision, status, criterion, variant, onlyErrors, sort]);

  const stale = calls.status === "error" && calls.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Inbox</h1>
          <p className="text-sm text-muted-foreground">Every call, most urgent first. Review means a person should look; it is not an alarm.</p>
        </div>
      </div>
      <UploadZone onUploaded={calls.reload} />

      <div className="flex flex-wrap items-center gap-3">
        <Select label="Decision" value={decision} onChange={(e) => setDecision(e.target.value)}>
          <option value="">all</option>
          <option value="alarm">alarm</option><option value="review">review</option><option value="no_alert">no alert</option>
        </Select>
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">all</option>
          {["queued", "processing", "done", "error"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <Select label="Criterion" value={criterion} onChange={(e) => setCriterion(e.target.value)}>
          <option value="">all</option>
          {CRITERIA.map((c) => <option key={c} value={c}>{c.replaceAll("_", " ")}</option>)}
        </Select>
        <Select label="Variant" value={variant} onChange={(e) => setVariant(e.target.value)}>
          <option value="">all</option>
          {VARIANTS.map((v) => <option key={v}>{v}</option>)}
        </Select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} />has stage errors</label>
        <div className="ml-auto"><Select label="Sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="default">decision, then risk</option><option value="risk">risk</option>
          <option value="confidence">confidence</option><option value="updated">last update</option>
        </Select></div>
      </div>

      {calls.status === "error" && <ErrorCard error={calls.error} title="Could not load the call list" onRetry={calls.reload} />}
      {stale && <p className="text-xs text-review">Showing the last good data. It may be stale.</p>}
      {gate.status === "error" && !gate.data && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-review bg-review-bg px-3 py-2 text-sm text-review">
          <span>The confidence gate could not be loaded ({gate.error.message}), so low-confidence calls are not flagged with ▼ below.</span>
          <button type="button" className="rounded border border-review px-2 py-0.5 text-xs" onClick={gate.reload}>Retry</button>
        </div>
      )}

      {calls.status === "loading" && !calls.data ? (
        <Card className="divide-y divide-border" aria-busy="true">
          {Array.from({ length: 8 }, (_, i) => <div key={i} className="flex gap-4 p-4"><Skeleton className="h-5 w-32" /><Skeleton className="h-5 w-24" /><Skeleton className="h-5 flex-1" /></div>)}
        </Card>
      ) : calls.data && calls.data.length === 0 ? (
        <EmptyState>No calls yet. Drop .wav files here or run <code className="font-mono">./run.sh &lt;folder&gt;</code>.</EmptyState>
      ) : rows.length === 0 && calls.data ? (
        <EmptyState>No call matches these filters. Clear a filter to see more.</EmptyState>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted-foreground">
              <tr>{["Call", "Status", "Decision", "Risk", "Confidence", "Criteria", "Duration", "Variant", "Updated"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r) => {
                const href = r.status === "processing" || r.status === "queued" ? `/calls/${r.call_id}/processing` : `/calls/${r.call_id}`;
                const dim = r.confidence != null && gate.data != null && r.confidence < gate.data;
                return (
                  <tr key={r.call_id} className="hover:bg-muted/60">
                    <td className="px-3 py-2.5"><Link href={href} className="font-mono font-medium underline-offset-2 hover:underline">{r.call_id}</Link></td>
                    <td className="px-3 py-2.5"><div className="flex flex-wrap gap-1.5"><StatusPill status={r.status} stage={stages[r.call_id]} /><StageErrorChip count={r.n_stage_errors} /></div></td>
                    <td className="px-3 py-2.5">{r.status === "queued" || r.status === "processing" ? null : <DecisionBadge decision={r.decision} />}</td>
                    <td className="w-40 px-3 py-2.5">{r.risk_score == null ? null : (
                      <div className="flex items-center gap-2"><ScoreBar value={r.risk_score} label="risk" color={r.decision === "alarm" ? "var(--alarm)" : r.decision === "review" ? "var(--review)" : "var(--noalert)"} /><span className="tabular w-10 text-right text-xs">{Math.round(r.risk_score * 100)}%</span></div>
                    )}</td>
                    <td className={`tabular px-3 py-2.5 ${dim ? "text-review" : ""}`} title={dim ? "below the confidence gate" : undefined}>
                      {r.confidence == null ? (r.status === "done" || r.status === "error" ? "n/a" : "") : `${Math.round(r.confidence * 100)}%${dim ? " ▼" : ""}`}
                    </td>
                    <td className="px-3 py-2.5"><div className="flex items-center gap-1">
                      {r.criteria[0] && <CriterionChip criterion={r.criteria[0]} />}
                      {r.criteria.length > 1 && <span className="text-xs text-muted-foreground" title={r.criteria.slice(1).join(", ")}>+{r.criteria.length - 1}</span>}
                    </div></td>
                    <td className="tabular px-3 py-2.5">{fmtTime(r.duration_s)}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{r.variant ?? "–"}</td>
                    <td className="tabular px-3 py-2.5 text-xs text-muted-foreground">{fmtDateTime(r.updated_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
      {calls.data && <p className="text-xs text-muted-foreground">{rows.length} of {calls.data.length} calls. <RiskConfidenceHint /></p>}
    </div>
  );
}

function RiskConfidenceHint() {
  return <span>Risk and confidence are always read together; confidence in amber with ▼ is below the gate.</span>;
}
