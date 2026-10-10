"use client";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";
import type { Term } from "@/lib/glossary";
import { useEffect, useRef } from "react";
import type { CallListItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The four big numbers at the top of the Overview, all counted from GET /api/calls. */
export function StatCards({ calls }: { calls: CallListItem[] | null }) {
  if (!calls) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-busy="true">
        {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
      </div>
    );
  }
  const finished = calls.filter((c) => c.status === "done" || c.status === "error");
  const alarms = finished.filter((c) => c.decision === "alarm").length;
  const reviews = finished.filter((c) => c.decision === "review").length;
  const running = calls.filter((c) => c.status === "queued" || c.status === "processing").length;
  const items = [
    { label: "Alarms", term: "alarm" as Term, value: alarms, hint: "suspicious passages with a reason", tone: alarms > 0 ? "text-alarm" : "" },
    { label: "To review", term: "review" as Term, value: reviews, hint: "unsure: a person decides, not an alarm", tone: reviews > 0 ? "text-review" : "" },
    { label: "Calls checked", term: "calls_checked" as Term, value: finished.length, hint: "every call, not samples", tone: "" },
    { label: "Processing", term: "processing" as Term, value: running, hint: running > 0 ? "analysis running now" : "nothing in the queue", tone: "" },
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((it) => (
        <div key={it.label} className="rounded-2xl border border-border bg-card px-5 py-4">
          <dt className="flex items-center gap-1 text-sm font-medium text-muted-foreground">{it.label}<InfoTip term={it.term} /></dt>
          <dd className={cn("tabular mt-1 text-4xl font-semibold tracking-tight", it.tone)}><CountUp value={it.value} /></dd>
          <dd className="mt-1 text-xs text-muted-foreground">{it.hint}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Counts up from 0 once, on first load (the page's one load moment). Later updates and reduced motion show the value at once.
 *  Written to the DOM directly with a timer: no re-render per step, and no dependency on animation frames. */
function CountUp({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const played = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (played.current || value === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = String(value); played.current = true; return;
    }
    played.current = true;
    const t0 = performance.now(), D = 700;
    let finished = false;
    el.textContent = "0";
    const timer = setInterval(() => {
      const k = Math.min(1, (performance.now() - t0) / D);
      el.textContent = String(Math.round(value * (1 - Math.pow(1 - k, 3))));
      if (k >= 1) { finished = true; clearInterval(timer); }
    }, 16);
    return () => { clearInterval(timer); el.textContent = String(value); if (!finished) played.current = false; };
  }, [value]);
  return <span ref={ref} aria-label={String(value)} />;
}
