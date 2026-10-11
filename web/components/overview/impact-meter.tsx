"use client";
// Impact meter (an ESTIMATE): today a bank listens to a small sample of calls; with Sentinel every call is checked and
// a person listens only to the calls it flags (alert + review). Inputs are the presenter's; the flagged share comes from
// the run on screen, re-decided exactly for each preset (POST /simulate). Every formula is printed under its number.
import { useMemo, useState } from "react";
import { Tween } from "@/components/ui/tween";
import { getCalls, getQualityEvidence, getThresholds } from "@/lib/data";
import { PRESETS } from "@/lib/presets";
import type { Decision } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { useSimulate } from "@/lib/use-simulate";
import { cn } from "@/lib/utils";

const fmt = (n: number, d = 0) => n.toLocaleString("de-CH", { maximumFractionDigits: d, minimumFractionDigits: d });

export function ImpactMeter() {
  const calls = useAsync(getCalls, "calls");
  const saved = useAsync(getThresholds, "thresholds");
  const [perDay, setPerDay] = useState(2000);
  const [sample, setSample] = useState(2);
  const [minManual, setMinManual] = useState(6);
  const [minFlagged, setMinFlagged] = useState(1.5);     // the officer plays the ±10 s passage and reads the reason
  const ev = useAsync(getQualityEvidence, "q-evidence");
  // escalation recall of the SHIPPED method, cross-validated out-of-fold (metrics/conditions_cv.json); the older
  // facts → rules cross-validation (metrics/crossval.json) is only the fallback for runs before the judge
  const { recall, recallSource } = useMemo(() => {
    const m = ev.data?.methods;
    if (m?.rows.length) {
      const mc = ev.data?.multi_check?.gate_pass ? ev.data.multi_check.rows.find((r) => /multi/i.test(r.method)) : null;   // shipped multi-check judge
      if (mc?.esc_r != null) return { recall: mc.esc_r, recallSource: "multi-check AI judge (shipped), zero-shot on all case calls" };
      const row = m.ship_rule_pass ? m.rows.find((r) => /conditions/i.test(r.name)) : m.rows.find((r) => /^S4 alone$/i.test(r.name));
      if (row?.oof?.esc_r != null) return { recall: row.oof.esc_r, recallSource: `${m.ship_rule_pass ? "AI judge + learned conditions" : "AI judge"} (shipped), 3-fold cross-validation, out-of-fold` };
    }
    const fin = ev.data?.crossval.find((r) => r.label === "final");
    const xs = Object.values(fin?.recall_folds ?? {}).filter((x): x is number => x != null);
    return xs.length ? { recall: xs.reduce((a, b) => a + b, 0) / xs.length, recallSource: "facts → rules, mean of 3 held-out folds" } : { recall: null, recallSource: "" };
  }, [ev.data]);
  const [preset, setPreset] = useState<number | null>(null);    // null = the run as decided
  const patch = preset == null || !saved.data ? null : { thresholds: { alarm: Math.max(PRESETS[preset].alarm, saved.data.review + 0.01) } };
  const sim = useSimulate(patch, 150);

  const counts = useMemo(() => {
    const c: Record<Decision, number> = { alarm: 0, review: 0, no_alert: 0 };
    for (const x of calls.data ?? []) if (x.decision && x.status !== "queued" && x.status !== "processing") c[x.decision] += 1;
    return c;
  }, [calls.data]);
  const used = patch && (sim.data ?? sim.stale) ? (sim.data ?? sim.stale)!.counts.after : counts;
  const n = used.alarm + used.review + used.no_alert;
  const flaggedShare = n ? (used.alarm + used.review) / n : 0;

  const todayCalls = perDay * sample / 100;
  const todayHours = todayCalls * minManual / 60;
  const withCalls = perDay * flaggedShare;
  const withHours = withCalls * minFlagged / 60;

  return (
    <section aria-labelledby="impact-h" className="elevated space-y-5 rounded-[var(--radius-panel)] p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="impact-h" className="text-title font-semibold">What it changes for a bank <span className="ml-2 rounded-full bg-review-bg px-3 py-0.5 align-middle text-xs font-semibold text-review">estimate</span></h2>
        <div role="group" aria-label="Sensitivity" className="flex flex-wrap gap-2">
          {[{ label: "This run", i: null as number | null }, ...PRESETS.map((p, i) => ({ label: p.label, i }))].map((p) => (
            <button key={p.label} type="button" aria-pressed={preset === p.i} onClick={() => setPreset(p.i)}
              className={cn("h-9 rounded-full border px-4 text-sm font-medium", preset === p.i ? "border-primary bg-primary text-primary-foreground" : "border-foreground/50 hover:bg-muted")}>{p.label}</button>
          ))}
        </div>
      </div>

      {recall != null && (
        <div className="rounded-2xl bg-muted/60 p-5">
          <p className="text-lead">
            Of every <b>100 calls that need a person</b>, <b className="tabular text-headline">{fmt(sample, 1)}</b> reach one today (a random {fmt(sample, 1)}% sample)
            {" "}vs <b className="tabular text-headline">{fmt(recall * 100)}</b> with Sentinel.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Today: a random sample finds risky calls at the sample rate. With Sentinel: escalation recall {fmt(recall, 2)} of the {recallSource}.
            It does not follow the presets (that would need the gold labels). Small samples: read it as a range, not a promise.
          </p>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Num label="Calls per day" value={perDay} set={setPerDay} min={0} step={100} />
        <Num label="Sampled today (%)" value={sample} set={setSample} min={0} max={100} step={0.5} />
        <Num label="Minutes per manual review" value={minManual} set={setMinManual} min={0} step={1} />
        <Num label="Minutes per flagged review (±10 s passage + reason)" value={minFlagged} set={setMinFlagged} min={0} step={0.5} />
      </div>

      <div className="grid gap-5 md:grid-cols-3">
        <Stat label="Calls checked" before={`${fmt(sample, 1)}%`} after="100%" formula="today: the sample rate · with Sentinel: every call is transcribed and checked" />
        <Stat label="Calls a person listens to per day" before={fmt(todayCalls)} after={<Tween value={withCalls} />}
          formula={`today: ${fmt(perDay)} × ${fmt(sample, 1)}% · with Sentinel: ${fmt(perDay)} × ${fmt(flaggedShare * 100, 1)}% flagged (${used.alarm} alerts + ${used.review} reviews of ${n} calls in this run${patch ? `, ${PRESETS[preset!].label.toLowerCase()} preset` : ""})`} />
        <Stat label="Officer hours per day" before={fmt(todayHours, 1)} after={<Tween value={withHours} format={(x) => fmt(x, 1)} />}
          formula={`calls listened to × minutes ÷ 60 (today ${fmt(minManual)} min per call, with Sentinel ${fmt(minFlagged, 1)} min per flagged review: the passage and the reason, not the whole call)`} />
      </div>
      <p className="text-xs text-muted-foreground">
        Estimate from the run on screen, not a forecast. With Sentinel the coverage is complete; how many risky calls are actually flagged depends on detection quality (see Quality), and the flagged share follows the alert line.
        {patch && sim.loading ? " Updating…" : ""}
      </p>
    </section>
  );
}

function Num({ label, value, set, min, max, step }: { label: string; value: number; set: (v: number) => void; min: number; max?: number; step: number }) {
  return (
    <label className="space-y-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input type="number" value={value} min={min} max={max} step={step} onChange={(e) => set(Math.max(min, Math.min(max ?? Infinity, Number(e.target.value) || 0)))}
        className="tabular h-11 w-full rounded-xl border border-border bg-background px-3 text-lead" />
    </label>
  );
}

function Stat({ label, before, after, formula }: { label: string; before: React.ReactNode; after: React.ReactNode; formula: string }) {
  return (
    <div className="space-y-1">
      <p className="eyebrow">{label}</p>
      <p className="tabular flex items-baseline gap-3"><span className="text-title text-muted-foreground">{before}</span><span aria-hidden className="text-muted-foreground">→</span><span className="text-headline font-semibold">{after}</span></p>
      <p className="text-xs text-muted-foreground"><span className="sr-only">Formula: </span>{formula}</p>
    </div>
  );
}
