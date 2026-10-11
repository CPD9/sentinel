"use client";
// Demo moment 4 in one glance: "your detection quality on the test set: false alarms and missed cases".
// Every number comes from the report's own counts; the three convention cards below stay the full picture.
import { pct } from "@/lib/format";
import { kindOf } from "./kind";
import type { QualityReport } from "@/lib/types";



export function Headline({ r }: { r: QualityReport }) {
  const esc = r.overall.escalation;       // gold alarm + review vs no_alert
  const strict = r.overall.strict_alarm;  // gold alarm vs everything else
  const needed = esc.tp + esc.fn;         // calls that needed attention
  const rec = esc.recall;
  const cards = [
    {
      label: "Caught", value: `${esc.tp} of ${needed}`,
      hint: rec.value == null ? "recall undefined (no call needed attention)"
        : `${pct(rec.value)} of the calls that needed attention were flagged (alert or review)${rec.ci_low != null ? ` · CI ${pct(rec.ci_low)}–${pct(rec.ci_high)}` : ""}`,
    },
    { label: "Missed", value: String(esc.fn), hint: "calls that needed attention but came out as no alert" },
    { label: "False alarms", value: String(strict.fp), hint: "alerts on calls that were harmless" },
  ];
  return (
    <section aria-labelledby="headline" className="space-y-3">
      <p id="headline" className="max-w-3xl text-base leading-relaxed">
        On <b>{r.overall.n} {kindOf(r).unseen ? "calls the system was never tuned on" : `calls it was tuned on (${kindOf(r).label}), so the numbers are optimistic`}</b>, Sentinel flagged <b>{esc.tp} of {needed}</b> calls that needed attention,
        missed <b>{esc.fn}</b> and raised <b>{strict.fp}</b> false alarm{strict.fp === 1 ? "" : "s"}.
      </p>
      <dl className="grid gap-3 sm:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="elevated rounded-[var(--radius-panel)] px-6 py-5">
            <dt className="eyebrow">{c.label}</dt>
            <dd className="tabular mt-1 text-4xl font-semibold tracking-tight">{c.value}</dd>
            <dd className="mt-1 text-xs text-muted-foreground">{c.hint}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
