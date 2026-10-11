"use client";
// The jury's words, as counts: false alarms and missed cases of the shipped system on the case calls, read from the
// final report (escalation: alert + review vs no alert). Until a threshold curve is published these are the counts at the
// shipped setting and do not move with the slider; the panel says so.
import { getQualityReport, getQualityReports } from "@/lib/data";
import type { QualityReport } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { kindOf } from "./kind";

export function pickShipped(rs: QualityReport[]): QualityReport | null {
  return rs.find((r) => kindOf(r).inSample && r.notes.some((n) => /judge/i.test(n))) ?? rs.find((r) => kindOf(r).inSample) ?? null;
}

export function OutcomeCounts({ note }: { note?: string }) {
  const rs = useAsync(async () => Promise.all((await getQualityReports()).map((x) => getQualityReport(x.report_id))), "q-all");
  const r = rs.data ? pickShipped(rs.data) : null;
  if (!r) return null;
  const e = r.overall.escalation;
  const items = [
    { label: "False alarms", value: e.fp, hint: "harmless calls sent to a person" },
    { label: "Missed cases", value: e.fn, hint: `of ${e.tp + e.fn} calls that needed a person` },
    { label: "Caught", value: e.tp, hint: "calls that needed a person and got one" },
  ];
  return (
    <section aria-label="False alarms and missed cases" className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
      <p className="eyebrow">False alarms and missed cases · shipped setting · {r.overall.n} case calls</p>
      <dl className="grid gap-4 sm:grid-cols-3">
        {items.map((i) => (
          <div key={i.label}><dt className="text-sm text-muted-foreground">{i.label}</dt><dd className="tabular text-headline font-semibold">{i.value}</dd><dd className="text-xs text-muted-foreground">{i.hint}</dd></div>
        ))}
      </dl>
      <p className="text-xs text-muted-foreground">{note ?? "Measured on the case calls at the shipped setting; they do not move with the slider until the threshold curve is published."}</p>
    </section>
  );
}
