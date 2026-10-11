"use client";
// Inbox (Nik's design 04): the call list on the left, the selected call on the right, both in view.
// Keyboard: j / k (or ↓ / ↑) move the selection, Enter opens the full call. Filters narrow the list; the counts in the
// group headers always describe what is shown.
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorCard } from "@/components/shell/states";
import { Skeleton } from "@/components/ui/skeleton";
import { CallList, GROUP_ORDER, callsIn, groupOf, type Group } from "./call-list";
import { CallPanel } from "./call-panel";
import { UploadButton, useWavUpload } from "./upload";
import { getCalls, getThresholds, getTrace, subscribeGlobalEvents } from "@/lib/data";
import { CRITERION_LABEL } from "@/lib/colors";
import { useReportMock } from "@/lib/mock-store";
import type { CallListItem, Criterion, DecisionTrace } from "@/lib/types";
import { CRITERIA } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const typing = (el: EventTarget | null) => el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName));

export function InboxView({ selected }: { selected: string | null }) {
  const router = useRouter();
  const calls = useAsync(getCalls, "calls");
  const th = useAsync(getThresholds, "thresholds");
  const [criterion, setCriterion] = useState("");
  const [variant, setVariant] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [stages, setStages] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);
  const [openState, setOpenState] = useState<Record<Group, boolean>>({ alarm: true, review: true, no_alert: false, processing: true });
  const upload = useWavUpload(calls.reload);

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

  // One trace per decided call, for the one-line reason on each row ("Unsure: noisy audio"). Missing traces are fine.
  const decidedKey = (calls.data ?? []).filter((c) => c.status === "done" || c.status === "error").map((c) => `${c.call_id}@${c.updated_at}`).join(",");
  const traces = useAsync(async () => {
    const ids = (calls.data ?? []).filter((c) => c.status === "done" || c.status === "error").map((c) => c.call_id);
    const got = await Promise.allSettled(ids.map((id) => getTrace(id)));
    return new Map(got.flatMap((r, i) => (r.status === "fulfilled" ? [[ids[i], r.value] as [string, DecisionTrace]] : [])));
  }, `traces:${decidedKey}`);

  const visible = useMemo(() => (calls.data ?? []).filter((r) =>
    (!criterion || r.criteria.includes(criterion as Criterion)) && (!variant || r.variant === variant) && (!onlyErrors || r.n_stage_errors > 0)),
  [calls.data, criterion, variant, onlyErrors]);
  const filtered = !!(criterion || variant || onlyErrors);

  // The call in the right panel: the one in the URL, else the first alert, else the first review, and so on.
  const current = useMemo(() => {
    const all = calls.data ?? [];
    return all.find((c) => c.call_id === selected)
      ?? (["alarm", "review", "no_alert", "processing"] as const).map((g) => callsIn(visible, g)[0]).find(Boolean) ?? null;
  }, [calls.data, visible, selected]);

  // The group of the selected call is always open (e.g. a shared link to a cleared call).
  const open = useMemo(() => (current ? { ...openState, [groupOf(current)]: true } : openState), [openState, current]);
  const setOpen = useCallback((g: Group, v: boolean) => setOpenState((o) => ({ ...o, [g]: v })), []);

  // j / k walk the rows in the order they are shown (open groups only); Enter opens the call.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      const order = GROUP_ORDER.filter((g) => open[g]).flatMap((g) => callsIn(visible, g));
      if (order.length === 0) return;
      const i = current ? order.findIndex((c) => c.call_id === current.call_id) : -1;
      const go = (c: CallListItem) => router.replace(`/?call=${encodeURIComponent(c.call_id)}`, { scroll: false });
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); go(order[Math.min(order.length - 1, i + 1)]); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); go(order[Math.max(0, i - 1)]); }
      else if (e.key === "Enter" && current && !(e.target instanceof HTMLButtonElement || e.target instanceof HTMLAnchorElement)) {
        e.preventDefault();
        router.push(current.status === "queued" || current.status === "processing" ? `/calls/${current.call_id}/processing` : `/calls/${current.call_id}`);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, visible, current, router]);

  const stale = calls.status === "error" && calls.data;

  return (
    <div className="relative space-y-4"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={(e) => { e.preventDefault(); setDragging(false); void upload.send(e.dataTransfer.files); }}>
      {dragging && (
        <div className="pointer-events-none fixed inset-3 z-40 flex items-center justify-center rounded-2xl border-2 border-dashed border-foreground bg-background/80 text-lg font-semibold">
          Drop .wav files to analyse them
        </div>
      )}
      <h1 className="sr-only">Alerts</h1>

      {calls.status === "error" && <ErrorCard error={calls.error} title="Could not load the call list" onRetry={calls.reload} />}
      {stale && <p className="text-xs text-review">Showing the last good data. It may be stale.</p>}
      {calls.data && calls.data.length === 0 ? (
        <EmptyState>No calls yet. Drop .wav files on this page or run <code className="font-mono">./run.sh &lt;folder&gt;</code>.</EmptyState>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
          <div className="stage-in space-y-3 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <FilterSelect label="Kind of fraud" value={criterion} onChange={setCriterion}
                options={CRITERIA.filter((c) => c !== "other").map((c) => [c, CRITERION_LABEL[c]])} />
              <FilterSelect label="Audio" value={variant} onChange={setVariant} options={[["clean", "clean"], ["noisy", "noisy"]]} />
              <label className="flex items-center gap-1.5 text-muted-foreground"><input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} />failed steps</label>
              <span className="ml-auto"><UploadButton upload={upload} /></span>
            </div>
            <p className="text-xs text-muted-foreground">
              {calls.data ? <>{filtered ? `${visible.length} of ${calls.data.length}` : calls.data.length} calls, every one checked · </> : null}
              <kbd className="rounded border border-border px-1 font-mono">j</kbd> <kbd className="rounded border border-border px-1 font-mono">k</kbd> to move,{" "}
              <kbd className="rounded border border-border px-1 font-mono">Enter</kbd> to open
            </p>
            {filtered && visible.length === 0 ? (
              <EmptyState>No call matches these filters. Clear a filter to see more.</EmptyState>
            ) : (
              <CallList calls={calls.data ? visible : null} selected={current?.call_id ?? null} stages={stages} traces={traces.data ?? new Map()} open={open} setOpen={setOpen} />
            )}
          </div>
          <div className="stage-in min-w-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto" style={{ "--i": 1 } as React.CSSProperties}>
            {current ? <CallPanel key={current.call_id} item={current} thresholds={th.data ?? null} />
              : calls.data ? null : <Skeleton className="h-96 rounded-[var(--radius-panel)]" />}
          </div>
        </div>
      )}
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1", value ? "border-foreground" : "border-border text-muted-foreground")}>
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="bg-transparent text-sm outline-none" aria-label={label}>
        <option value="">{label}: all</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}
