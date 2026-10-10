"use client";
import { Skeleton } from "@/components/ui/skeleton";
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
    { label: "Alarms", value: alarms, hint: "suspicious passages with a reason", tone: alarms > 0 ? "text-alarm" : "" },
    { label: "To review", value: reviews, hint: "unsure: a person decides, not an alarm", tone: reviews > 0 ? "text-review" : "" },
    { label: "Calls checked", value: finished.length, hint: "every call, not samples", tone: "" },
    { label: "Processing", value: running, hint: running > 0 ? "analysis running now" : "nothing in the queue", tone: "" },
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((it) => (
        <div key={it.label} className="rounded-2xl border border-border bg-card px-5 py-4">
          <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{it.label}</dt>
          <dd className={cn("tabular mt-1 text-4xl font-semibold tracking-tight", it.tone)}>{it.value}</dd>
          <dd className="mt-1 text-xs text-muted-foreground">{it.hint}</dd>
        </div>
      ))}
    </dl>
  );
}
