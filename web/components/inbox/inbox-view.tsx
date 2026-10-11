"use client";
// Overview: one control bar, then either two panels (List) or the full table (Table).
//   bar     group tabs with counts (Alarms · To review · No alert · Processing)   |   List / Table switch
//   List    the calls of the chosen group | the open call (CallPanel), both the same height, each scrolling on its own
//   Table   every call with filters and sorting; a row opens that call in the List view
// URL: ?call=<id> (the open call; empty = closed), ?tab=<group> (only needed when no call says it), ?view=table.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LayoutList, MousePointerClick, Table2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Segmented, type SegmentedOption } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { Select } from "@/components/ui/select";
import { CriterionChip, DecisionBadge, StageErrorChip, StatusPill } from "@/components/shell/badges";
import { EmptyState, ErrorCard } from "@/components/shell/states";
import { ScoreBar } from "@/components/shell/score";
import { CallList, GROUPS, callsIn, groupOf, type Group } from "./call-list";
import { CallPanel } from "./call-panel";
import { useUpload } from "./upload";
import { getCalls, getThresholds, subscribeGlobalEvents } from "@/lib/data";
import { fmtDateTime, fmtTime } from "@/lib/format";
import { useReportMock } from "@/lib/mock-store";
import type { CallListItem, Criterion, Decision } from "@/lib/types";
import { CRITERIA, VARIANTS } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const DECISION_RANK: Record<string, number> = { alarm: 0, review: 1, no_alert: 2 };
const decisionRank = (d: Decision | null) => (d == null ? -1 : DECISION_RANK[d]);
const PILL: Record<Group, { pill: string; ring: string }> = {
  alarm: { pill: "var(--alarm-bg)", ring: "color-mix(in srgb, var(--alarm) 40%, transparent)" },
  review: { pill: "var(--review-bg)", ring: "color-mix(in srgb, var(--review) 45%, transparent)" },
  no_alert: { pill: "var(--noalert-bg)", ring: "color-mix(in srgb, var(--noalert) 35%, transparent)" },
  processing: { pill: "var(--info-bg)", ring: "color-mix(in srgb, var(--info) 40%, transparent)" },
};
const isGroup = (x: string | null): x is Group => x === "alarm" || x === "review" || x === "no_alert" || x === "processing";

type Sort = "default" | "risk" | "confidence" | "updated";
type View = "list" | "table";

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

/** The Overview URL for a state; defaults are left out so links stay short. */
function overviewHref({ call, tab, view }: { call?: string | null; tab?: Group | null; view?: View }) {
  const q = new URLSearchParams();
  if (view === "table") q.set("view", "table");
  if (tab) q.set("tab", tab);
  if (call != null) q.set("call", call);
  const s = q.toString();
  return s ? `/?${s}` : "/";
}

export function InboxView({ selected, tab: tabParam, view }: { selected: string | null; tab: string | null; view: View }) {
  const router = useRouter();
  const calls = useAsync(getCalls, "calls");
  const th = useAsync(getThresholds, "thresholds");
  const [stages, setStages] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);
  const upload = useUpload();
  const reloadCalls = calls.reload;
  // An import finished (from the nav button or a drop here): fetch the list again.
  useEffect(() => { if (upload.imported) reloadCalls(); }, [upload.imported, reloadCalls]);

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

  const all = useMemo(() => calls.data ?? [], [calls.data]);
  const stale = calls.status === "error" && calls.data;
  const nProcessing = all.filter((c) => groupOf(c) === "processing").length;

  // The open call: the one in the URL, else the first call of the tab in the URL, else the first alarm, review, …
  // `?call=` with an empty id means the officer closed the panel.
  const closed = selected === "";
  const current = useMemo(() => {
    if (closed) return null;
    const byId = all.find((c) => c.call_id === selected);
    if (byId) return byId;
    if (isGroup(tabParam)) return callsIn(all, tabParam)[0] ?? null;
    return (["alarm", "review", "no_alert", "processing"] as const).map((g) => callsIn(all, g)[0]).find(Boolean) ?? null;
  }, [all, selected, closed, tabParam]);
  // The tab: the URL's, else the open call's group, else Alarms. Processing only exists while something runs.
  const wanted: Group = isGroup(tabParam) ? tabParam : current ? groupOf(current) : "alarm";
  const tab: Group = wanted === "processing" && nProcessing === 0 ? "alarm" : wanted;

  // direction of the last tab change, so the rows slide in from the side the officer moved to
  const order = GROUPS.map((g) => g.key);
  // (adjusting state while rendering, React's pattern for "react to a value change")
  const [lastTab, setLastTab] = useState(tab);
  const [dir, setDir] = useState<1 | -1>(1);
  if (lastTab !== tab) {
    setDir(order.indexOf(tab) >= order.indexOf(lastTab) ? 1 : -1);
    setLastTab(tab);
  }

  const go = (state: Parameters<typeof overviewHref>[0]) => router.replace(overviewHref(state), { scroll: false });
  // Switching tabs opens that group's first call (keeps the panel closed if the officer closed it).
  const pickTab = (g: Group) => go({ tab: g, call: closed ? "" : callsIn(all, g)[0]?.call_id ?? "" });

  // ↑ / ↓ move to the previous / next call of the tab (not while typing or on a slider).
  const tabRows = useMemo(() => callsIn(all, tab), [all, tab]);
  useEffect(() => {
    if (view !== "list") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const t = e.target as HTMLElement | null;
      if (t?.closest("input, textarea, select, [contenteditable], [role=slider], [role=tablist]")) return;
      const i = tabRows.findIndex((c) => c.call_id === current?.call_id);
      const next = tabRows[e.key === "ArrowDown" ? Math.min(tabRows.length - 1, i + 1) : Math.max(0, i - 1)];
      if (!next || next.call_id === current?.call_id) return;
      e.preventDefault();
      router.replace(overviewHref({ call: next.call_id }), { scroll: false });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, tabRows, current, router]);

  // On a phone the panel sits below the list: after picking another call, glide down to it (not on the first load).
  const panelRef = useRef<HTMLDivElement>(null);
  const firstCall = useRef(true);
  const openId = current?.call_id ?? null;
  useEffect(() => {
    if (firstCall.current) { firstCall.current = false; return; }
    if (openId && window.matchMedia("(max-width: 1023px)").matches) {
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      panelRef.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    }
  }, [openId]);

  const tabs: SegmentedOption<Group>[] = GROUPS
    .filter((g) => g.key !== "processing" || nProcessing > 0)
    .map((g) => ({
      key: g.key, label: g.title, count: callsIn(all, g.key).length, ...PILL[g.key], hideLabelOnPhone: true,
      icon: <g.icon className={cn("size-4", g.color, g.key === "processing" && "animate-spin motion-reduce:animate-none")} aria-hidden />,
    }));
  const views: SegmentedOption<View>[] = [
    { key: "list", label: "List", icon: <LayoutList className="size-4" aria-hidden />, hideLabelOnPhone: true },
    { key: "table", label: "Table", icon: <Table2 className="size-4" aria-hidden />, hideLabelOnPhone: true },
  ];

  return (
    <div className="relative space-y-4"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={(e) => { e.preventDefault(); setDragging(false); void upload.send(e.dataTransfer.files); }}>
      {dragging && (
        <div className="pointer-events-none fixed inset-3 z-40 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-background/80 text-lg font-semibold text-link">
          Drop .wav files to import them
        </div>
      )}

      {/* the control bar: which calls (left), how to show them (right) */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {view === "list"
          ? <Segmented label="Calls by decision" options={tabs} value={tab} onChange={pickTab} />
          : <p className="text-sm text-muted-foreground">All {all.length} calls, every one checked automatically, not sampled.</p>}
        <Segmented label="View" size="sm" options={views} value={view} onChange={(v) => go({ view: v, call: current?.call_id ?? (closed ? "" : null) })} />
      </div>

      {calls.status === "error" && <ErrorCard error={calls.error} title="Could not load the call list" onRetry={calls.reload} />}
      {stale && <p className="text-xs text-review">Showing the last good data. It may be stale.</p>}
      {calls.data && calls.data.length === 0 ? (
        <EmptyState>No calls yet. Drop .wav files on this page or run <code className="font-mono">./run.sh &lt;folder&gt;</code>.</EmptyState>
      ) : view === "table" ? (
        <div key="table" className="view-in"><CallsTable calls={calls.data ?? null} gate={th.data?.confidence_gate ?? null} stages={stages} /></div>
      ) : (
        // Two panels of the same height on wide screens, each scrolling on its own; stacked (list first) on narrow ones.
        <div key="list" className="view-in grid gap-4 lg:h-[calc(100vh-10rem)] lg:min-h-[30rem] lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div className="surface-tint flex min-h-0 flex-col rounded-2xl">
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              <CallList calls={calls.data ?? null} group={tab} selected={current?.call_id ?? null} stages={stages} dir={dir} />
            </div>
            <p className="hidden border-t border-border px-4 py-2 text-xs text-muted-foreground lg:block">
              {all.length} calls, every one checked automatically, not sampled · <kbd className="font-sans">↑</kbd> <kbd className="font-sans">↓</kbd> to move, <kbd className="font-sans">Esc</kbd> to close
            </p>
          </div>
          <div ref={panelRef} className="min-h-0 min-w-0 scroll-mt-16 max-lg:min-h-[calc(100svh-5rem)] lg:overflow-y-auto lg:rounded-2xl">
            {current ? <CallPanel key={current.call_id} item={current} thresholds={th.data ?? null} />
              : calls.data ? <NoCallOpen />
              : <Skeleton className="h-96 rounded-2xl" />}
          </div>
        </div>
      )}
    </div>
  );
}

/** Right panel when no call is open. */
function NoCallOpen() {
  return (
    <div className="panel-in flex h-full min-h-64 flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border px-6 py-12 text-center">
      <MousePointerClick className="size-6 text-muted-foreground" aria-hidden />
      <p className="font-medium">No call open</p>
      <p className="max-w-xs text-sm text-muted-foreground">Pick a call on the left to see what was said, the risk and why it was flagged.</p>
    </div>
  );
}

/** Every call in one table with filters and sorting. A finished call opens in the List view; a running one shows its progress. */
function CallsTable({ calls, gate, stages }: { calls: CallListItem[] | null; gate: number | null; stages: Record<string, string> }) {
  const [decision, setDecision] = useState("");
  const [status, setStatus] = useState("");
  const [criterion, setCriterion] = useState("");
  const [variant, setVariant] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [sort, setSort] = useState<Sort>("default");

  const rows = useMemo(() => sortRows((calls ?? []).filter((r) =>
    (!decision || r.decision === decision) && (!status || r.status === status) &&
    (!criterion || r.criteria.includes(criterion as Criterion)) && (!variant || r.variant === variant) &&
    (!onlyErrors || r.n_stage_errors > 0)), sort), [calls, decision, status, criterion, variant, onlyErrors, sort]);

  return (
    <div className="elevated space-y-4 rounded-2xl p-4">
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

      {!calls ? (
        <Card className="divide-y divide-border" aria-busy="true">
          {Array.from({ length: 8 }, (_, i) => <div key={i} className="flex gap-4 p-4"><Skeleton className="h-5 w-32" /><Skeleton className="h-5 w-24" /><Skeleton className="h-5 flex-1" /></div>)}
        </Card>
      ) : rows.length === 0 ? (
        <EmptyState>No call matches these filters. Clear a filter to see more.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted-foreground">
              <tr>{["Call", "Status", "Decision", "Risk", "Confidence", "Criteria", "Duration", "Variant", "Updated"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r, i) => {
                const running = r.status === "processing" || r.status === "queued";
                const href = running ? `/calls/${r.call_id}/processing` : overviewHref({ call: r.call_id });
                const dim = r.confidence != null && gate != null && r.confidence < gate;
                return (
                  <tr key={r.call_id} className="row-in transition-colors hover:bg-muted/60" style={{ "--dir": 0, animationDelay: `${Math.min(i, 15) * 18}ms` } as React.CSSProperties}>
                    <td className="px-3 py-2.5"><Link href={href} title={running ? "Watch progress" : "Open in the list"} className="font-mono font-medium text-link underline-offset-2 hover:underline">{r.call_id}</Link></td>
                    <td className="px-3 py-2.5"><div className="flex flex-wrap gap-1.5"><StatusPill status={r.status} stage={stages[r.call_id]} /><StageErrorChip count={r.n_stage_errors} /></div></td>
                    <td className="px-3 py-2.5">{running ? null : <DecisionBadge decision={r.decision} />}</td>
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
        </div>
      )}
      {calls && <p className="text-xs text-muted-foreground">{rows.length} of {calls.length} calls. Risk and confidence are always read together; confidence in amber with ▼ is below the gate.</p>}
    </div>
  );
}
