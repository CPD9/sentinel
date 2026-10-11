"use client";
// Demo moment 4 in one glance: "your detection quality on the test set: false alarms and missed cases".
// Every number comes from the report's own counts; the three convention cards below stay the full picture.
import { pct } from "@/lib/format";
import type { QualityReport } from "@/lib/types";

const WHERE: Record<QualityReport["split"], string> = {
  test: "test calls the system was never tuned on",
  holdout: "held-out calls the system was never tuned on",
  dev: "development calls (used for tuning, so the numbers are optimistic)",
};

export function Headline({ r }: { r: QualityReport }) {
  const esc = r.overall.escalation;       // gold alarm + review vs no_alert
  const strict = r.overall.strict_alarm;  // gold alarm vs everything else
  const needed = esc.tp + esc.fn;         // calls that needed attention
  const rec = esc.recall;
  const cards = [
    {
      label: "Caught", value: `${esc.tp} of ${needed}`,
      hint: rec.value == null ? "recall undefined (no call needed attention)"
        : `${pct(rec.value)} of the calls that needed attention were flagged (alarm or review)${rec.ci_low != null ? ` · CI ${pct(rec.ci_low)}–${pct(rec.ci_high)}` : ""}`,
    },
    { label: "Missed", value: String(esc.fn), hint: "calls that needed attention but came out as no alert" },
    { label: "False alarms", value: String(strict.fp), hint: "alarms raised on calls that should not be an alarm" },
  ];
  return (
    <section aria-labelledby="headline" className="space-y-3">
      <p id="headline" className="max-w-3xl text-base leading-relaxed">
        On <b>{r.overall.n} {WHERE[r.split]}</b>, the system flagged <b>{esc.tp} of {needed}</b> calls that needed attention,
        missed <b>{esc.fn}</b> and raised <b>{strict.fp}</b> false alarm{strict.fp === 1 ? "" : "s"}.
      </p>
      <dl className="grid gap-3 sm:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-2xl border border-border bg-card px-5 py-4">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{c.label}</dt>
            <dd className="tabular mt-1 text-4xl font-semibold tracking-tight">{c.value}</dd>
            <dd className="mt-1 text-xs text-muted-foreground">{c.hint}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
