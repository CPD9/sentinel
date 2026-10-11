import type { Workload } from "@/lib/types";

/** Officer workload = alerts + reviews per 100 calls. Two stacked bars (now / with the draft) and one plain sentence. */
export function WorkloadMeter({ before, after, delta }: { before: Workload; after: Workload; delta: number }) {
  const line = delta === 0 ? "No change in officer workload." : delta < 0
    ? `Officers would get ${Math.abs(delta).toFixed(1)} fewer calls per 100 to look at.`
    : `Officers would get ${delta.toFixed(1)} more calls per 100 to look at.`;
  return (
    <section aria-label="Officer workload" className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Officer workload</h3>
        <span className="text-[11px] text-muted-foreground">alerts + reviews per 100 calls</span>
      </div>
      {([["Now", before], ["With draft", after]] as const).map(([label, w]) => (
        <div key={label} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-2 text-xs">
          <span className="text-muted-foreground">{label}</span>
          <div role="img" aria-label={`${label}: ${w.alarms_per_100} alerts and ${w.reviews_per_100} reviews per 100 calls`}
            className="flex h-3 overflow-hidden rounded-sm bg-muted">
            <div className="bg-alarm" style={{ width: `${Math.min(100, w.alarms_per_100)}%` }} />
            <div className="border-l border-background bg-review" style={{ width: `${Math.min(100 - Math.min(100, w.alarms_per_100), w.reviews_per_100)}%` }} />
          </div>
          <span className="tabular w-24 text-right"><b>{w.flagged_per_100.toFixed(1)}</b> <span className="text-muted-foreground">({w.alarms_per_100.toFixed(0)}+{w.reviews_per_100.toFixed(0)})</span></span>
        </div>
      ))}
      <p className={`text-xs ${delta < 0 ? "text-ok" : delta > 0 ? "text-review" : "text-muted-foreground"}`}>{line}</p>
      <p className="text-[11px] text-muted-foreground"><span className="inline-block size-2 rounded-sm bg-alarm align-middle" /> alerts <span className="ml-2 inline-block size-2 rounded-sm bg-review align-middle" /> reviews · over {after.n} calls with a decision</p>
    </section>
  );
}
