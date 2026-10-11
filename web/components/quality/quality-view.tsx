"use client";
import { ChevronRight, Lock } from "lucide-react";
import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { DocGate, EmptyState, ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { CurveChart } from "@/components/settings/curve-chart";
import { getQualityReport, getQualityReports } from "@/lib/data";
import { fmtDateTime, fmtMetric, humanize, pct } from "@/lib/format";
import { useReportMock } from "@/lib/mock-store";
import type { ConventionSet, QualityReport } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { AblationChart, GroupBars, LatencyBars, METRICS, ReliabilityDiagram, WerChart, type MetricKey } from "./charts";
import { Headline } from "./headline";
import { kindOf } from "./kind";
import { Prove } from "./prove";
import { SameSentence } from "./same-sentence";
import { BigMetric, MetricBar } from "./metric";
import { cn } from "@/lib/utils";
import { DECISION_LABEL } from "@/lib/explain";

export function QualityView() {
  const list = useAsync(getQualityReports, "q-list");
  const [picked, setId] = useState<string | null>(null);
  // Open the UNSEEN report first: that is the honest headline; tuned-on numbers are optimistic by construction.
  const reports = useAsync(async () => Promise.all((await getQualityReports()).map((x) => getQualityReport(x.report_id))), "q-all");
  const unseenFirst = reports.data?.find((r) => kindOf(r).unseen)?.report_id;
  const id = picked ?? unseenFirst ?? list.data?.[0]?.report_id ?? null;
  const report = useAsync(() => (id ? getQualityReport(id) : Promise.reject(new Error("none"))), `q:${id}`);
  useReportMock("quality", report.data);

  return (
    <div className="stage-in space-y-6">
      <div className="space-y-1">
        <h1 className="text-headline font-semibold tracking-tight">Quality</h1>
        <p className="text-body text-muted-foreground">How well the system finds fraud. The cross-validated number comes first; every other number says whether the system was tuned on those calls or never saw them.</p>
      </div>
      {reports.data && <Prove reports={reports.data} />}
      <SameSentence />
      {reports.data && reports.data.length > 1 && <><h2 className="eyebrow pt-2">Each report in detail</h2><Compare reports={reports.data} active={id} onPick={setId} /></>}
      {list.status === "loading" && !list.data && <SkeletonBlock rows={6} />}
      {list.status === "error" && !list.data && <ErrorCard error={list.error} onRetry={list.reload} />}
      {list.data && list.data.length === 0 && (
        <EmptyState>
          No quality report yet. The final evaluation is being produced; this page fills itself as soon as the report file
          (<code className="font-mono">artifacts/quality/final_report.json</code>) exists. Nothing here is estimated in the meantime.
        </EmptyState>
      )}
      {id && <DocGate state={report} unavailable="This report is not available." rows={8}>{(r) => <Report r={r} />}</DocGate>}
    </div>
  );
}

function Report({ r }: { r: QualityReport }) {
  const [metric, setMetric] = useState<MetricKey>("escalation.recall");
  const small = r.overall.n < 30;
  const hidden = (what: string) => <p className="text-sm text-muted-foreground">{what}: not computed for this run.</p>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {kindOf(r).unseen ? <Pill><Lock className="size-3.5" aria-hidden />Unseen: run once with the frozen settings</Pill>
          : <Pill tone="review">Tuned on these calls ({kindOf(r).label}): numbers are optimistic</Pill>}
        <Pill tone={small ? "review" : undefined}>{r.overall.n} calls{small ? " · small sample, read the ranges" : ""}</Pill>
        <Pill>{r.mode === "asr" ? "speech-recognition transcripts" : "reference transcripts"}</Pill>
        {r.is_mock && <Pill tone="mock">Mock data</Pill>}
      </div>
      <Headline r={r} />
      {r.warnings.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-sm text-review">{r.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}

      <div className="grid gap-5 lg:grid-cols-3">
        <ConventionCard title="Strict" desc="Only alerts count as flagged" cs={r.overall} kind="strict_alarm"
          labels={["Flagged calls that were real fraud", "Real fraud calls that were caught"]} />
        <ConventionCard title="Escalation" desc="Alerts and reviews count as flagged" cs={r.overall} kind="escalation"
          labels={["Flagged calls that needed a person", "Calls needing a person that were flagged"]} />
        <StrictDetail cs={r.overall} />
      </div>

      <details className="text-sm"><summary className="cursor-pointer text-xs text-muted-foreground">Run details: {r.split} split · {r.mode} transcripts · {r.system}</summary>
        <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {[["run", r.run_id], ["system", r.system], ["provider", r.provider], ["mode", r.mode], ["split", r.split], ["n", String(r.overall.n)],
            ["ranges", `${r.bootstrap.n_resamples} bootstrap resamples · ${pct(r.bootstrap.ci_level)} interval · unit: ${r.bootstrap.unit}`]].map(([k, v]) => (
            <div key={k} className="flex gap-1.5"><dt className="text-muted-foreground">{k}</dt><dd className="font-mono text-xs leading-5">{v}</dd></div>
          ))}
        </dl>
      </details>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><div><CardTitle>Three classes</CardTitle><CardDescription>alert / review / no alert, all counted</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <MetricBar label="macro F1" m={r.overall.three_class.macro_f1} />
            <MetricBar label="accuracy" m={r.overall.three_class.accuracy} />
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader><div><CardTitle>Every call, three classes</CardTitle><CardDescription>rows = what was true, columns = what the system said · n = {r.overall.n}</CardDescription></div></CardHeader>
          <CardContent className="overflow-x-auto"><Confusion cs={r.overall} /></CardContent>
        </Card>
      </div>

      <Panel title="Breakdowns" desc="Per Stufe and clean vs noisy, with bootstrap CIs. Small groups have wide intervals."
        action={<Select label="Metric" value={metric} onChange={(e) => setMetric(e.target.value as MetricKey)}>{(Object.keys(METRICS) as MetricKey[]).map((k) => <option key={k} value={k}>{METRICS[k][0]}</option>)}</Select>}>
        <div className="grid gap-4 md:grid-cols-2">
          {r.breakdowns.stufe ? <div><h4 className="mb-1 text-xs font-semibold">Per Stufe</h4><GroupBars groups={r.breakdowns.stufe} metric={metric} label="Stufe" /></div> : hidden("Per-Stufe breakdown")}
          {r.breakdowns.variant ? <div><h4 className="mb-1 text-xs font-semibold">Clean vs noisy</h4><GroupBars groups={r.breakdowns.variant} metric={metric} label="" /></div> : hidden("Clean/noisy breakdown")}
        </div>
      </Panel>

      <Panel title="Ablations" desc="Escalation recall: keyword-only vs LLM-only vs combined, on reference and ASR transcripts.">{r.ablations.length ? <AblationChart items={r.ablations} /> : hidden("Ablations")}</Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Evidence validity" desc="Flagged passages with valid segment refs, timestamps inside the audio and a playable snippet.">
          {r.evidence_validity ? (
            <div className="space-y-2">
              <p className="text-sm"><b className="tabular text-lg">{pct(r.evidence_validity.item_validity_rate, 1)}</b> of {r.evidence_validity.n_items} passages fully valid ({r.evidence_validity.n_valid_items})</p>
              {Object.entries(r.evidence_validity.per_check_pass_rate).map(([k, v]) => (
                <div key={k} className="grid grid-cols-[10rem_1fr_3.5rem] items-center gap-2 text-sm"><span>{humanize(k)}</span><div className="h-2 rounded-full bg-muted"><div className="h-2 rounded-full bg-ok" style={{ width: `${v * 100}%` }} /></div><span className="tabular text-right text-xs">{pct(v, 1)}</span></div>
              ))}
              {r.evidence_validity.checks_skipped.length > 0 && <div className="rounded-md bg-muted p-2 text-xs"><b>Checks skipped:</b><ul className="list-disc pl-4">{r.evidence_validity.checks_skipped.map((c) => <li key={c}>{c}</li>)}</ul></div>}
            </div>
          ) : hidden("Evidence validity")}
        </Panel>
      </div>
      <details className="group space-y-4">
        <summary className="flex cursor-pointer list-none items-center gap-2 rounded-2xl border border-border bg-card/40 px-4 py-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
          <ChevronRight className="size-4 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
          More analysis <span className="font-normal text-muted-foreground">· threshold curves, confidence reliability, transcript quality vs recall, speed per step</span>
        </summary>
        <div className="space-y-4 pt-4">
      <Panel title="Threshold curves" desc="Precision and recall as one threshold moves; the marker is the value used in this run.">
        {r.threshold_curves.length === 0 ? hidden("Threshold curves") : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{r.threshold_curves.map((c, i) => (
            <div key={i}><h4 className="mb-1 text-xs font-semibold">{humanize(c.param)} · {humanize(c.convention)}</h4><CurveChart curve={c} /></div>
          ))}</div>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Confidence reliability" desc="Does a confidence of 80 % mean right 80 % of the time?">{r.reliability ? <ReliabilityDiagram r={r.reliability} /> : hidden("Reliability")}</Panel>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="WER vs downstream recall" desc="Does a worse transcript cost recall?">{r.wer_vs_recall.length ? <WerChart bins={r.wer_vs_recall} /> : hidden("WER vs recall")}</Panel>
        <Panel title="Per-stage latency" desc="Bar = p50, whisker to p95.">{r.latency.length ? <LatencyBars items={r.latency} /> : hidden("Latency")}</Panel>
      </div>
        </div>
      </details>
      {r.notes.length > 0 && <ul className="list-disc pl-5 text-xs text-muted-foreground">{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </div>
  );
}

function Panel({ title, desc, action, children }: { title: string; desc: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card><CardHeader><div><CardTitle>{title}</CardTitle><CardDescription>{desc}</CardDescription></div>{action}</CardHeader><CardContent>{children}</CardContent></Card>
  );
}

function ConventionCard({ title, desc, cs, kind, labels }: { title: string; desc: string; cs: ConventionSet; kind: "strict_alarm" | "escalation"; labels: [string, string] }) {
  const b = cs[kind];
  return (
    <section className="elevated space-y-5 rounded-[var(--radius-panel)] p-6">
      <div><h3 className="text-title font-semibold">{title}</h3><p className="text-sm text-muted-foreground">{desc}</p></div>
      <BigMetric label={labels[0]} m={b.precision} term="precision" />
      <BigMetric label={labels[1]} m={b.recall} term="recall" />
      <p className="tabular text-xs text-muted-foreground">F1 {fmtMetric(b.f1.value)} · counts {b.tp} / {b.fp} / {b.fn} / {b.tn} (caught / false alarm / missed / all-clear)</p>
    </section>
  );
}

/** Nik's design 06 third card: every call, by what the system said and what was true (strict convention). */
function StrictDetail({ cs }: { cs: ConventionSet }) {
  const b = cs.strict_alarm;
  const cell = (n: number, word: string, bad: boolean) => (
    <div className={cn("grid h-24 place-content-center rounded-xl text-center", bad ? "bg-alarm-bg" : "bg-muted")}>
      <p className="tabular text-headline font-semibold">{n}</p><p className="text-sm">{word}</p>
    </div>
  );
  return (
    <section className="elevated space-y-4 rounded-[var(--radius-panel)] p-6">
      <div><h3 className="text-title font-semibold">Strict, in detail</h3><p className="text-sm text-muted-foreground">Every call, by what the system said and what was true</p></div>
      <div className="grid grid-cols-[5.5rem_1fr_1fr] items-center gap-2 text-sm">
        <span /><span className="text-center font-semibold">Was fraud</span><span className="text-center font-semibold">Was harmless</span>
        <span className="text-right text-muted-foreground">Said alert</span>{cell(b.tp, "caught", false)}{cell(b.fp, "false alarm", true)}
        <span className="text-right text-muted-foreground">Said no alert</span>{cell(b.fn, "missed", true)}{cell(b.tn, "correct all-clear", false)}
      </div>
      <p className="text-xs text-muted-foreground">“Said no alert” here includes reviews: in the strict count only an alert counts as flagged.</p>
    </section>
  );
}

/** Tuned-on vs unseen, side by side: the same two numbers for every report, each one a button that opens it. */
function Compare({ reports, active, onPick }: { reports: QualityReport[]; active: string | null; onPick: (id: string) => void }) {
  const sorted = [...reports].sort((a, b) => Number(kindOf(b).unseen) - Number(kindOf(a).unseen));
  const p = (m: { value: number | null; ci_low: number | null; ci_high: number | null }) =>
    m.value == null ? "n/a" : `${Math.round(m.value * 100)}%${m.ci_low != null ? ` (${Math.round(m.ci_low * 100)}–${Math.round(m.ci_high! * 100)})` : ""}`;
  return (
    <div role="group" aria-label="Reports" className="grid gap-3 md:grid-cols-3">
      {sorted.map((r) => {
        const k = kindOf(r), on = r.report_id === active, e = r.overall.escalation;
        return (
          <button key={r.report_id} type="button" aria-pressed={on} onClick={() => onPick(r.report_id)}
            className={cn("rounded-2xl border p-4 text-left transition-colors", on ? "border-foreground bg-muted" : "border-border hover:bg-muted/60")}>
            <p className={cn("text-sm font-semibold", k.unseen ? "" : "text-review")}>{k.inSample ? "In-sample" : k.unseen ? "Unseen" : "Tuned on"} · {k.label}</p>
            <p className="text-xs text-muted-foreground">{r.overall.n} calls · {r.mode === "asr" ? "speech recognition" : "reference transcripts"}</p>
            <p className="tabular mt-2 text-sm">Calls needing a person that were flagged: <b>{e.tp} of {e.tp + e.fn}</b> {p(e.recall)}</p>
            <p className="tabular text-sm">Flagged calls that needed a person: <b>{p(e.precision)}</b></p>
          </button>
        );
      })}
    </div>
  );
}

function Pill({ children, tone }: { children: React.ReactNode; tone?: "review" | "mock" }) {
  return <span className={cn("inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium", tone === "mock" ? "bg-review text-[#1a1300]" : tone === "review" ? "bg-review-bg text-review" : "bg-muted")}>{children}</span>;
}

function Confusion({ cs }: { cs: ConventionSet }) {
  const labels = cs.three_class.labels;
  const max = Math.max(1, ...labels.flatMap((g) => labels.map((p) => cs.three_class.confusion[g]?.[p] ?? 0)));
  return (
    <table className="text-sm" aria-label="Confusion matrix, rows gold, columns predicted">
      <thead><tr><th className="p-1 text-xs font-normal text-muted-foreground">true ↓ / said →</th>{labels.map((l) => <th key={l} className="px-3 py-1 text-xs font-semibold">{DECISION_LABEL[l]}</th>)}</tr></thead>
      <tbody>{labels.map((g) => (
        <tr key={g}><th className="px-3 py-1 text-right text-xs font-semibold">{DECISION_LABEL[g]}</th>
          {labels.map((p) => { const v = cs.three_class.confusion[g]?.[p] ?? 0; return (
            <td key={p} className="tabular h-12 w-24 border border-border text-center text-base font-semibold"
              style={{ background: `color-mix(in srgb, var(${g === p ? "--ok" : "--alarm"}) ${Math.round((v / max) * 45)}%, var(--card))` }}>{v}</td>); })}
        </tr>))}</tbody>
    </table>
  );
}

