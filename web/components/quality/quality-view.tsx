"use client";
import { Lock } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
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
import { MetricBar } from "./metric";

export function QualityView() {
  const list = useAsync(getQualityReports, "q-list");
  const [picked, setId] = useState<string | null>(null);
  const id = picked ?? list.data?.[0]?.report_id ?? null;
  const report = useAsync(() => (id ? getQualityReport(id) : Promise.reject(new Error("none"))), `q:${id}`);
  useReportMock("quality", report.data);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Quality lab</h1>
          <p className="text-sm text-muted-foreground">Three metric conventions are always shown together, each with a bootstrap confidence interval.</p>
        </div>
        {list.data && list.data.length > 0 && (
          <Select label="Report" value={id ?? ""} onChange={(e) => setId(e.target.value)} className="max-w-xs">
            {list.data.map((r) => <option key={r.report_id} value={r.report_id}>{r.split} · {r.mode} · {r.system} · {fmtDateTime(r.created_at)}</option>)}
          </Select>
        )}
      </div>
      {list.status === "loading" && !list.data && <SkeletonBlock rows={6} />}
      {list.status === "error" && !list.data && <ErrorCard error={list.error} onRetry={list.reload} />}
      {list.data && list.data.length === 0 && <EmptyState>No evaluation run yet. Run <code className="font-mono">python -m pipeline.evaluate --pred …</code>.</EmptyState>}
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
      <Card>
        <CardContent className="space-y-2">
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {[["run", r.run_id], ["system", r.system], ["mode", r.mode], ["split", r.split], ["n", String(r.overall.n)],
              ["bootstrap", `${r.bootstrap.n_resamples} resamples · ${pct(r.bootstrap.ci_level)} CI · unit: ${r.bootstrap.unit}`]].map(([k, v]) => (
              <div key={k} className="flex gap-1.5"><dt className="text-muted-foreground">{k}</dt><dd className="font-mono text-xs leading-5">{v}</dd></div>
            ))}
          </dl>
          <div className="flex flex-wrap gap-2">
            {r.split === "test" && <Badge className="border-foreground"><Lock className="size-3" />locked test set — final report only</Badge>}
            {small && <Badge className="border-review bg-review-bg text-review">n is small ({r.overall.n} &lt; 30): read the intervals, not the point estimates</Badge>}
            {r.is_mock && <Badge className="border-review text-review">MOCK report</Badge>}
          </div>
          {r.warnings.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-sm text-review">{r.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <ConventionCard title="Strict alarm" desc="alarm vs everything else" cs={r.overall} kind="strict_alarm" />
        <ConventionCard title="Escalation" desc="alarm + review vs no alert" cs={r.overall} kind="escalation" />
        <Card>
          <CardHeader><div><CardTitle>3-class</CardTitle><CardDescription>alarm / review / no alert</CardDescription></div></CardHeader>
          <CardContent className="space-y-3">
            <MetricBar label="macro F1" m={r.overall.three_class.macro_f1} />
            <MetricBar label="accuracy" m={r.overall.three_class.accuracy} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><div><CardTitle>Confusion matrix</CardTitle><CardDescription>rows = gold, columns = predicted · n = {r.overall.n}</CardDescription></div></CardHeader>
        <CardContent><Confusion cs={r.overall} /></CardContent>
      </Card>

      <Panel title="Threshold curves" desc="Precision and recall as one threshold moves; the marker is the value used in this run.">
        {r.threshold_curves.length === 0 ? hidden("Threshold curves") : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{r.threshold_curves.map((c, i) => (
            <div key={i}><h4 className="mb-1 text-xs font-semibold">{humanize(c.param)} · {humanize(c.convention)}</h4><CurveChart curve={c} /></div>
          ))}</div>
        )}
      </Panel>

      <Panel title="Breakdowns" desc="Per Stufe and clean vs noisy, with bootstrap CIs. Small groups have wide intervals."
        action={<Select label="Metric" value={metric} onChange={(e) => setMetric(e.target.value as MetricKey)}>{(Object.keys(METRICS) as MetricKey[]).map((k) => <option key={k} value={k}>{METRICS[k][0]}</option>)}</Select>}>
        <div className="grid gap-4 md:grid-cols-2">
          {r.breakdowns.stufe ? <div><h4 className="mb-1 text-xs font-semibold">Per Stufe</h4><GroupBars groups={r.breakdowns.stufe} metric={metric} label="Stufe" /></div> : hidden("Per-Stufe breakdown")}
          {r.breakdowns.variant ? <div><h4 className="mb-1 text-xs font-semibold">Clean vs noisy</h4><GroupBars groups={r.breakdowns.variant} metric={metric} label="" /></div> : hidden("Clean/noisy breakdown")}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Confidence reliability" desc="Does a confidence of 80 % mean right 80 % of the time?">{r.reliability ? <ReliabilityDiagram r={r.reliability} /> : hidden("Reliability")}</Panel>
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

      <Panel title="Ablations" desc="Escalation recall: keyword-only vs LLM-only vs combined, on reference and ASR transcripts.">{r.ablations.length ? <AblationChart items={r.ablations} /> : hidden("Ablations")}</Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="WER vs downstream recall" desc="Does a worse transcript cost recall?">{r.wer_vs_recall.length ? <WerChart bins={r.wer_vs_recall} /> : hidden("WER vs recall")}</Panel>
        <Panel title="Per-stage latency" desc="Bar = p50, whisker to p95.">{r.latency.length ? <LatencyBars items={r.latency} /> : hidden("Latency")}</Panel>
      </div>
      {r.notes.length > 0 && <ul className="list-disc pl-5 text-xs text-muted-foreground">{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </div>
  );
}

function Panel({ title, desc, action, children }: { title: string; desc: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card><CardHeader><div><CardTitle>{title}</CardTitle><CardDescription>{desc}</CardDescription></div>{action}</CardHeader><CardContent>{children}</CardContent></Card>
  );
}

function ConventionCard({ title, desc, cs, kind }: { title: string; desc: string; cs: ConventionSet; kind: "strict_alarm" | "escalation" }) {
  const b = cs[kind];
  return (
    <Card>
      <CardHeader><div><CardTitle>{title}</CardTitle><CardDescription>{desc}</CardDescription></div></CardHeader>
      <CardContent className="space-y-3">
        <MetricBar label="precision" m={b.precision} />
        <MetricBar label="recall" m={b.recall} />
        <MetricBar label="F1" m={b.f1} />
        <p className="tabular text-xs text-muted-foreground">TP {b.tp} · FP {b.fp} · FN {b.fn} · TN {b.tn}</p>
      </CardContent>
    </Card>
  );
}

function Confusion({ cs }: { cs: ConventionSet }) {
  const labels = cs.three_class.labels;
  const max = Math.max(1, ...labels.flatMap((g) => labels.map((p) => cs.three_class.confusion[g]?.[p] ?? 0)));
  return (
    <table className="text-sm" aria-label="Confusion matrix, rows gold, columns predicted">
      <thead><tr><th className="p-1 text-xs font-normal text-muted-foreground">gold ↓ / predicted →</th>{labels.map((l) => <th key={l} className="px-3 py-1 text-xs font-semibold">{humanize(l)}</th>)}</tr></thead>
      <tbody>{labels.map((g) => (
        <tr key={g}><th className="px-3 py-1 text-right text-xs font-semibold">{humanize(g)}</th>
          {labels.map((p) => { const v = cs.three_class.confusion[g]?.[p] ?? 0; return (
            <td key={p} className="tabular h-12 w-24 border border-border text-center text-base font-semibold"
              style={{ background: `color-mix(in srgb, var(${g === p ? "--ok" : "--alarm"}) ${Math.round((v / max) * 45)}%, var(--card))` }}>{v}</td>); })}
        </tr>))}</tbody>
    </table>
  );
}

