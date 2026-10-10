"use client";
import { Bar, BarChart, CartesianGrid, ErrorBar, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtMetric, fmtSeconds, pct } from "@/lib/format";
import type { Ablation, ConventionSet, Metric, Reliability, StageLatency, WerBin } from "@/lib/types";

const AX = { fill: "var(--axis)", fontSize: 11 };
const TIP = { background: "var(--card)", border: "1px solid var(--border)", fontSize: 12 } as const;
const err = (m: Metric): [number, number] | undefined => (m.value != null && m.ci_low != null ? [m.value - m.ci_low, m.ci_high! - m.value] : undefined);

export const METRICS = {
  "strict_alarm.precision": ["Strict alarm · precision", (c: ConventionSet) => c.strict_alarm.precision],
  "strict_alarm.recall": ["Strict alarm · recall", (c: ConventionSet) => c.strict_alarm.recall],
  "escalation.precision": ["Escalation · precision", (c: ConventionSet) => c.escalation.precision],
  "escalation.recall": ["Escalation · recall", (c: ConventionSet) => c.escalation.recall],
  "three_class.macro_f1": ["3-class · macro F1", (c: ConventionSet) => c.three_class.macro_f1],
  "three_class.accuracy": ["3-class · accuracy", (c: ConventionSet) => c.three_class.accuracy],
} as const;
export type MetricKey = keyof typeof METRICS;

/** Bars per group with bootstrap CI whiskers. Undefined metrics are left empty and listed as n/a, never drawn as 0. */
export function GroupBars({ groups, metric, label }: { groups: Record<string, ConventionSet>; metric: MetricKey; label: string }) {
  const get = METRICS[metric][1];
  const data = Object.entries(groups).map(([k, cs]) => ({ name: `${label} ${k} (n=${cs.n})`, value: get(cs).value ?? undefined, err: err(get(cs)), undefinedMetric: get(cs).value == null }));
  return (
    <div>
      <div className="h-56 w-full" role="img" aria-label={`${METRICS[metric][0]} by ${label}`}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="name" tick={AX} interval={0} />
            <YAxis domain={[0, 1]} tick={AX} width={52} label={{ value: "score (0–1)", angle: -90, position: "insideLeft", offset: 6, style: { textAnchor: "middle" }, fill: "var(--axis)", fontSize: 11 }} />
            <Tooltip contentStyle={TIP} formatter={(v) => (typeof v === "number" ? v.toFixed(2) : "n/a")} />
            <Bar dataKey="value" fill="var(--c-insider_trading)" isAnimationActive={false} maxBarSize={56}><ErrorBar dataKey="err" stroke="var(--foreground)" width={6} strokeWidth={1.5} /></Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {data.some((d) => d.undefinedMetric) && <p className="text-xs text-muted-foreground">n/a (undefined): {data.filter((d) => d.undefinedMetric).map((d) => d.name).join(", ")}</p>}
    </div>
  );
}

export function AblationChart({ items }: { items: Ablation[] }) {
  const names = ["keyword_only", "llm_only", "combined"] as const;
  const row = (name: string, transcript: "reference" | "asr") => items.find((a) => a.name === name && a.transcript === transcript)?.conventions.escalation.recall;
  const data = names.map((n) => ({
    name: n.replace("_", " "),
    reference: row(n, "reference")?.value ?? undefined, referenceErr: row(n, "reference") && err(row(n, "reference")!),
    asr: row(n, "asr")?.value ?? undefined, asrErr: row(n, "asr") && err(row(n, "asr")!),
  }));
  return (
    <div className="h-64 w-full" role="img" aria-label="Escalation recall by ablation and transcript type">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="name" tick={AX} />
          <YAxis domain={[0, 1]} tick={AX} width={52} label={{ value: "escalation recall (0–1)", angle: -90, position: "insideLeft", offset: 6, style: { textAnchor: "middle" }, fill: "var(--axis)", fontSize: 11 }} />
          <Tooltip contentStyle={TIP} formatter={(v) => (typeof v === "number" ? v.toFixed(2) : "n/a")} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="reference" name="reference transcript" fill="var(--c-third_party_disclosure)" isAnimationActive={false}><ErrorBar dataKey="referenceErr" stroke="var(--foreground)" width={5} /></Bar>
          <Bar dataKey="asr" name="ASR transcript" fill="var(--c-credential_sharing)" isAnimationActive={false}><ErrorBar dataKey="asrErr" stroke="var(--foreground)" width={5} /></Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function WerChart({ bins }: { bins: WerBin[] }) {
  const data = bins.map((b) => ({ name: `${pct(b.wer_lo)}–${pct(b.wer_hi)} (n=${b.n})`, value: b.escalation_recall.value ?? undefined, err: err(b.escalation_recall) }));
  return (
    <div className="h-56 w-full" role="img" aria-label="Escalation recall by word error rate bin">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="name" tick={AX} interval={0} label={{ value: "word error rate bin (n = gold-escalated calls)", position: "insideBottom", offset: -10, fill: "var(--axis)", fontSize: 11 }} />
          <YAxis domain={[0, 1]} tick={AX} width={52} label={{ value: "escalation recall (0–1)", angle: -90, position: "insideLeft", offset: 6, style: { textAnchor: "middle" }, fill: "var(--axis)", fontSize: 11 }} />
          <Tooltip contentStyle={TIP} formatter={(v) => (typeof v === "number" ? v.toFixed(2) : "n/a")} />
          <Bar dataKey="value" name="escalation recall" fill="var(--c-control_evasion)" isAnimationActive={false} maxBarSize={56}><ErrorBar dataKey="err" stroke="var(--foreground)" width={6} /></Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Reliability diagram: bar height = accuracy in the bin, bar width ∝ n, diagonal = perfect calibration. */
export function ReliabilityDiagram({ r }: { r: Reliability }) {
  const W = 420, H = 260, L = 40, B = 34, T = 10, R = 10;
  const pw = W - L - R, ph = H - T - B;
  const x = (v: number) => L + v * pw, y = (v: number) => T + (1 - v) * ph;
  const maxN = Math.max(1, ...r.bins.map((b) => b.n));
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[520px]" role="img" aria-label="Reliability diagram: confidence against accuracy per bin">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (<g key={t}>
          <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} stroke="var(--grid)" /><text x={L - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="var(--axis)">{t}</text>
          <line x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} stroke="var(--grid)" /><text x={x(t)} y={y(0) + 13} textAnchor="middle" fontSize={10} fill="var(--axis)">{t}</text>
        </g>))}
        {r.bins.map((b, i) => {
          if (b.n === 0 || b.accuracy == null || b.mean_confidence == null) return null;
          const bw = Math.max(6, (b.n / maxN) * (x(b.hi) - x(b.lo)) * 0.9);
          return (<g key={i}>
            <rect x={x(b.mean_confidence) - bw / 2} width={bw} y={y(b.accuracy)} height={y(0) - y(b.accuracy)} fill="var(--c-insider_trading)" opacity={0.8} />
            <text x={x(b.mean_confidence)} y={y(b.accuracy) - 3} textAnchor="middle" fontSize={9} fill="var(--foreground)">n={b.n}</text>
          </g>);
        })}
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="var(--foreground)" strokeDasharray="4 3" />
        <text x={x(0.5)} y={H - 4} textAnchor="middle" fontSize={11} fill="var(--axis)">mean confidence in bin (0–1)</text>
        <text transform={`translate(10 ${y(0.5)}) rotate(-90)`} textAnchor="middle" fontSize={11} fill="var(--axis)">accuracy (0–1)</text>
      </svg>
      <figcaption className="text-xs text-muted-foreground">Bar width ∝ calls in the bin. Dashed line = perfect calibration. “Correct” = {r.correctness}. Empty bins are not drawn.</figcaption>
      <p className="mt-1 text-sm">ECE <b className="tabular">{fmtMetric(r.ece.value)}</b>{r.ece.ci_low != null && <span className="tabular text-muted-foreground"> (CI {r.ece.ci_low.toFixed(2)}–{r.ece.ci_high!.toFixed(2)})</span>}</p>
    </figure>
  );
}

/** p50 bar with a p95 whisker per stage. */
export function LatencyBars({ items }: { items: StageLatency[] }) {
  const max = Math.max(...items.map((s) => s.p95_s), 0.001);
  return (
    <ul className="space-y-1.5" aria-label="Per-stage latency">
      {items.map((s) => (
        <li key={s.stage} className="grid grid-cols-[6rem_1fr_9rem] items-center gap-2 text-sm">
          <span className="font-mono text-xs">{s.stage}</span>
          <div className="relative h-4" role="img" aria-label={`${s.stage} p50 ${s.p50_s} s, p95 ${s.p95_s} s`}>
            <div className="absolute inset-y-1 left-0 rounded-sm bg-foreground/70" style={{ width: `${(s.p50_s / max) * 100}%`, minWidth: 2 }} />
            <div className="absolute top-1/2 h-px bg-foreground" style={{ left: `${(s.p50_s / max) * 100}%`, width: `${((s.p95_s - s.p50_s) / max) * 100}%` }} />
            <div className="absolute top-0.5 h-3 w-px bg-foreground" style={{ left: `${(s.p95_s / max) * 100}%` }} />
          </div>
          <span className="tabular text-right text-xs text-muted-foreground">p50 {fmtSeconds(s.p50_s)} · p95 {fmtSeconds(s.p95_s)}</span>
        </li>
      ))}
    </ul>
  );
}
