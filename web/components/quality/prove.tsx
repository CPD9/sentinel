"use client";
// Prove step, top of the Quality page: the cross-validated number first, the trivial baselines next to it, the pre-fix
// unseen result kept in view, and what we found and changed. Every number is read from the run's files
// (metrics/crossval.json, the strategy comparison summary, the quality reports); a baseline that is true by definition
// says so, and a range that was not computed says so.
import { getQualityEvidence } from "@/lib/data";
import type { QualityReport } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { kindOf } from "./kind";

const f2 = (v: number | null | undefined) => (v == null ? "n/a" : v.toFixed(2));
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const STEP: Record<string, string> = { "1_reseg": "+ re-segmentation of the transcript", "2_asr_prompt": "+ extraction prompt written for speech transcripts", "3_keyword_floor": "+ keyword floor (not shipped)", final: "shipped" };

export function Prove({ reports }: { reports: QualityReport[] }) {
  const ev = useAsync(getQualityEvidence, "q-evidence");
  if (!ev.data) return null;
  const { crossval, strategies, auc } = ev.data;
  const fin = crossval.find((r) => r.label === "final") ?? crossval.at(-1) ?? null;
  const flagAll = fin?.flag_all ? mean(Object.values(fin.flag_all)) : null;
  const first = crossval[0] ?? null;
  const prefixUnseen = reports.find((r) => kindOf(r).prefix && kindOf(r).unseen) ?? null;
  const inSample = reports.find((r) => kindOf(r).inSample) ?? null;
  const s1 = strategies?.rows.find((r) => r.id === "S1") ?? null;
  if (!fin) return null;

  return (
    <section aria-labelledby="prove-h" className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="elevated space-y-2 rounded-[var(--radius-panel)] p-6">
          <p id="prove-h" className="eyebrow">The number to quote · 3-fold cross-validation</p>
          <p className="tabular flex flex-wrap items-baseline gap-x-4">
            <span className="text-display font-semibold">{f2(fin.cv_mean)}</span>
            <span className="text-lead text-muted-foreground">escalation F1, folds {f2(fin.cv_min)}–{f2(fin.cv_max)}</span>
          </p>
          <p className="text-sm text-muted-foreground">
            Settings tuned on two splits, scored on the third, rotated over dev, Testset_30 and holdout (dialogue-grouped). Per fold:{" "}
            {Object.entries(fin.folds).map(([k, v]) => `${k} ${f2(v)}`).join(" · ")}.
          </p>
          {flagAll != null && (
            <p className="text-sm font-medium text-review">Below the trivial baseline: sending every call to review scores {f2(flagAll)} under the same cross-validation.</p>
          )}
        </div>
        <div className="elevated space-y-2 rounded-[var(--radius-panel)] p-6">
          <p className="eyebrow">Kept on record</p>
          {prefixUnseen && (
            <p className="tabular"><span className="text-headline font-semibold">{f2(prefixUnseen.overall.escalation.f1.value)}</span>
              <span className="ml-2 text-sm text-muted-foreground">escalation F1 of the pre-fix system on the {prefixUnseen.overall.n} unseen holdout calls, run once before any change</span></p>
          )}
          {inSample && (
            <p className="tabular text-sm"><b>{f2(inSample.overall.escalation.f1.value)}</b>{inSample.overall.escalation.f1.ci_low != null && ` [${f2(inSample.overall.escalation.f1.ci_low)}, ${f2(inSample.overall.escalation.f1.ci_high)}]`}
              <span className="text-muted-foreground"> on all {inSample.overall.n} case calls after the fix: in-sample (tuned on them), so optimistic. The independent test is the jury&rsquo;s hidden set.</span></p>
          )}
        </div>
      </div>

      <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
        <p className="eyebrow">Against baselines (escalation: alert + review vs no alert)</p>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th className="py-1.5 pr-4 font-medium">Method</th><th className="py-1.5 pr-4 font-medium">Escalation F1</th><th className="py-1.5 pr-4 font-medium">Ranking (AUC)</th><th className="py-1.5 font-medium">Measured on</th></tr>
          </thead>
          <tbody className="tabular divide-y divide-border align-top">
            <tr><td className="py-2 pr-4 font-semibold">Flag all (everything to review)</td><td className="py-2 pr-4">{f2(flagAll)}</td><td className="py-2 pr-4">0.50 <span className="text-muted-foreground">(constant score, by definition)</span></td><td className="py-2 text-muted-foreground">3-fold CV, speech transcripts</td></tr>
            <tr><td className="py-2 pr-4 font-semibold">Flag none</td><td className="py-2 pr-4">0.00 <span className="text-muted-foreground">(nothing flagged, by definition)</span></td><td className="py-2 pr-4">0.50 <span className="text-muted-foreground">(by definition)</span></td><td className="py-2 text-muted-foreground">–</td></tr>
            {s1 && <tr><td className="py-2 pr-4 font-semibold">Keywords only</td><td className="py-2 pr-4">{f2(s1.esc_f1)}{s1.ci && ` [${f2(s1.ci[0])}, ${f2(s1.ci[1])}]`}</td><td className="py-2 pr-4 text-muted-foreground">not computed</td><td className="py-2 text-muted-foreground">{strategies?.tuning_set ?? "tuning set"}, {s1.n} calls</td></tr>}
            <tr className="font-semibold"><td className="py-2 pr-4">Facts → rules (shipped)</td><td className="py-2 pr-4">{f2(fin.cv_mean)} <span className="font-normal text-muted-foreground">({f2(fin.cv_min)}–{f2(fin.cv_max)})</span></td>
              <td className="py-2 pr-4">{auc ? <>{f2(auc.value)} <span className="font-normal text-muted-foreground">(below chance; range not computed)</span></> : <span className="font-normal text-muted-foreground">not computed</span>}</td>
              <td className="py-2 font-normal text-muted-foreground">3-fold CV, speech transcripts{auc ? `; AUC on all 62 calls, in-sample (${auc.run_id ?? "final run"})` : ""}</td></tr>
          </tbody>
        </table>
        <p className="text-xs text-muted-foreground">AUC: how well the risk score ranks calls that needed a person above those that did not; 0.50 is a coin flip.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
          <p className="eyebrow">What we found</p>
          <p className="text-body leading-relaxed">
            Our first decision method was <b>no better than chance</b>: its risk score ranks calls {auc ? `worse than a coin (AUC ${f2(auc.value)})` : "no better than a coin"}, and no setting beats
            sending every call to review. We measured it instead of tuning it away, kept the pre-fix result{prefixUnseen ? ` (${f2(prefixUnseen.overall.escalation.f1.value)} on the unseen holdout)` : ""} on record,
            and fixed the speech path: transcripts re-cut at sentence ends and an extraction prompt written for speech transcripts. Cross-validated escalation F1 went from {f2(first?.cv_mean)} to {f2(fin.cv_mean)}.
          </p>
          <p className="text-sm text-muted-foreground">Still open: the ranking stays below chance and below the trivial baseline. Next: a direct judgement of the whole call on speech transcripts, keeping the facts as evidence; being measured now.</p>
        </div>
        <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
          <p className="eyebrow">Each change, cross-validated</p>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 pr-3 font-medium">Step</th><th className="py-1 pr-3 font-medium">3-fold CV F1</th><th className="py-1 font-medium">All 62, in-sample</th></tr></thead>
            <tbody className="tabular divide-y divide-border">
              {crossval.map((r) => (
                <tr key={r.label} className={r.label === "final" ? "font-semibold" : ""}>
                  <td className="py-1.5 pr-3">{STEP[r.label] ?? r.label}</td><td className="py-1.5 pr-3">{f2(r.cv_mean)} <span className="font-normal text-muted-foreground">({f2(r.cv_min)}–{f2(r.cv_max)})</span></td><td className="py-1.5">{f2(r.all62)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
