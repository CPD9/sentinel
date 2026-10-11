"use client";
// Prove step, top of the Quality page: the cross-validated number first, the trivial baselines next to it, the pre-fix
// unseen result kept in view, and what we found and changed. Every number is read from the run's files
// (metrics/crossval.json, the strategy comparison summary, the quality reports); a baseline that is true by definition
// says so, and a range that was not computed says so.
import { getQualityEvidence } from "@/lib/data";
import type { QualityEvidence, QualityReport } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { kindOf } from "./kind";

const f2 = (v: number | null | undefined) => (v == null ? "n/a" : v.toFixed(2));
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const STEP: Record<string, string> = { "1_reseg": "+ re-segmentation of the transcript", "2_asr_prompt": "+ extraction prompt written for speech transcripts", "3_keyword_floor": "+ keyword floor (not shipped)", final: "shipped" };

export function Prove({ reports }: { reports: QualityReport[] }) {
  const ev = useAsync(getQualityEvidence, "q-evidence");
  if (!ev.data) return null;
  if (ev.data.methods?.rows.length) return <JudgeProve ev={ev.data} reports={reports} />;
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

const pct0 = (v: number | null | undefined) => (v == null ? "n/a" : `${Math.round(v * 100)}%`);
const range = (ci: [number, number] | null | undefined) => (ci ? ` [${f2(ci[0])}, ${f2(ci[1])}]` : "");

/** The judge era: one CV protocol for every method (metrics/conditions_cv.json, out-of-fold over dev / Testset_30 /
 *  holdout), AUC with its 95% range from metrics/judge_eval.json, the headline from the final report. */
function JudgeProve({ ev, reports }: { ev: QualityEvidence; reports: QualityReport[] }) {
  const rows = ev.methods!.rows;
  const by = (re: RegExp) => rows.find((r) => re.test(r.name)) ?? null;
  const auc = (re: RegExp) => Object.entries(ev.judge_eval?.auc ?? {}).find(([k]) => re.test(k))?.[1] ?? null;
  const judge = by(/^S4 alone$/i), cond = by(/conditions/i), facts = by(/facts/i), flagAll = by(/flag-all/i);
  const shipped = ev.methods!.ship_rule_pass ? cond : judge;
  const fin = reports.find((r) => kindOf(r).inSample && r.notes.some((n) => /judge/i.test(n))) ?? null;
  const prefix = reports.find((r) => kindOf(r).prefix && kindOf(r).unseen) ?? null;
  const e = fin?.overall.escalation;
  const zeroShot = fin?.notes.some((n) => /no tuned parameter/i.test(n));
  // multi-check judge (shipped when its gate passed): one zero-shot check per criterion, on all case calls
  const mc = ev.multi_check?.gate_pass ? ev.multi_check.rows.find((r) => /multi/i.test(r.method)) ?? null : null;
  const pos = e ? e.tp + e.fn : null;                                   // calls that need a person (from the final report)
  const mcCaught = mc?.esc_r != null && pos ? Math.round(mc.esc_r * pos) : null;
  const mcF1 = mc?.esc_p != null && mc.esc_r != null && mc.esc_p + mc.esc_r > 0 ? (2 * mc.esc_p * mc.esc_r) / (mc.esc_p + mc.esc_r) : null;
  const headAuc = mc?.auc != null ? { value: mc.auc, ci: mc.auc_ci } : auc(/S4|judge/i);
  type LadderRow = { label: string; note?: string; f1: number | null | undefined; r?: number | null; p?: number | null; bacc?: number | null; load?: number | null; fa?: number | null; auc?: { value: number | null; ci: [number, number] | null } | null; strong?: boolean; muted?: boolean };
  const ladder: { label: string; note?: string; f1: number | null | undefined; r?: number | null; p?: number | null; bacc?: number | null; load?: number | null; fa?: number | null; auc?: { value: number | null; ci: [number, number] | null } | null; strong?: boolean; muted?: boolean }[] = [
    { label: "Pre-fix system (facts → rules, before the speech fix)", note: `unseen holdout, ${prefix?.overall.n ?? "–"} calls, run once`, f1: prefix?.overall.escalation.f1.value ?? null, r: prefix?.overall.escalation.recall.value ?? null },
    { label: "Facts → rules", f1: facts?.oof?.esc_f1, r: facts?.oof?.esc_r, p: facts?.oof?.esc_p, bacc: facts?.oof?.bacc, load: facts?.oof?.review_load, fa: facts?.oof?.false_alarms, auc: auc(/facts/i) },
    { label: mc ? "Single AI judge (one verdict per call)" : `AI judge${ev.methods!.ship_rule_pass ? "" : " (shipped)"}`, note: mc ? "zero-shot, so out-of-fold = all calls" : undefined, f1: judge?.oof?.esc_f1, r: judge?.oof?.esc_r, p: judge?.oof?.esc_p, bacc: judge?.oof?.bacc, load: judge?.oof?.review_load, fa: judge?.oof?.false_alarms, auc: auc(/S4|judge/i), strong: !mc && !ev.methods!.ship_rule_pass },
    ...(cond ? [{ label: `AI judge + learned review conditions${ev.methods!.ship_rule_pass ? " (shipped)" : ""}`, note: ev.methods!.ship_rule_pass ? undefined : "not shipped: did not beat the judge alone under cross-validation", f1: cond.oof?.esc_f1, r: cond.oof?.esc_r, p: cond.oof?.esc_p, bacc: cond.oof?.bacc, load: cond.oof?.review_load, fa: cond.oof?.false_alarms, strong: !!ev.methods!.ship_rule_pass, muted: !ev.methods!.ship_rule_pass }] : []),
    ...(mc ? [{ label: "Multi-check judge (shipped)", note: "one zero-shot check per criterion, risk = the highest; all calls, nothing tuned on them", f1: mcF1, r: mc.esc_r, p: mc.esc_p,
      bacc: mc.bacc, load: mc.review_load, fa: mc.false_alarms, auc: mc.auc != null ? { value: mc.auc, ci: mc.auc_ci } : null, strong: true }] : []),
  ];
  const base: LadderRow[] = [
    { label: "Flag all (everything to review)", f1: flagAll?.oof?.esc_f1, r: flagAll?.oof?.esc_r, p: flagAll?.oof?.esc_p, bacc: flagAll?.oof?.bacc, load: flagAll?.oof?.review_load, fa: flagAll?.oof?.false_alarms, auc: auc(/flag-all/i) },
    { label: "Flag none", f1: 0, r: 0, p: null, bacc: 0.5, load: 0, fa: 0, auc: auc(/flag-none/i) },
    { label: "Keywords only", f1: null, auc: auc(/keyword/i) },
  ];

  return (
    <section aria-labelledby="prove-h" className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="elevated space-y-2 rounded-[var(--radius-panel)] p-6">
          <p id="prove-h" className="eyebrow">The decision: an AI judge reads the whole call</p>
          {mc && pos != null && mcCaught != null ? (
            <>
              <p className="text-headline font-semibold leading-tight">{mc.false_alarms === 0 ? "0 false alarms" : `${mc.false_alarms} false alarms`} in {fin!.overall.n} calls</p>
              <p className="tabular text-lead"><b>{pos - mcCaught}</b> missed cases · <b>{mc.false_alarms}</b> false alarms · <b>{mcCaught}</b> caught</p>
              <p className="text-lead">it finds <b className="tabular">{mcCaught} of {pos}</b> calls that need a person: recall <b className="tabular">{f2(mc.esc_r)}</b>, up from {f2(judge?.oof?.esc_r)} with one verdict per call.</p>
              <p className="text-sm text-muted-foreground">Multi-check judge: one zero-shot check per criterion, no parameter tuned on these calls. The independent test is the jury&rsquo;s hidden set.</p>
            </>
          ) : e && fin ? (
            <>
              <p className="text-headline font-semibold leading-tight">{e.fp === 0 ? "0 false alarms" : `${e.fp} false alarm${e.fp === 1 ? "" : "s"}`} in {fin.overall.n} calls</p>
              <p className="tabular text-lead"><b>{e.fn}</b> missed case{e.fn === 1 ? "" : "s"} · <b>{e.fp}</b> false alarm{e.fp === 1 ? "" : "s"} · <b>{e.tp}</b> caught</p>
              <p className="text-lead">but it finds <b className="tabular">{e.tp} of {e.tp + e.fn}</b> calls that need a person: recall <b className="tabular">{f2(e.recall.value)}</b>{range(e.recall.ci_low != null ? [e.recall.ci_low, e.recall.ci_high!] : null)}.</p>
              <p className="text-sm text-muted-foreground">{zeroShot ? "Zero-shot: no parameter was tuned on these calls, so these numbers are effectively unseen. " : ""}The independent test is the jury&rsquo;s hidden set.</p>
            </>
          ) : <p className="text-sm text-muted-foreground">The final report for the judge is not in this run yet.</p>}
        </div>
        <div className="elevated space-y-2 rounded-[var(--radius-panel)] p-6">
          <p className="eyebrow">How well it ranks calls (AUC, 95% range)</p>
          {headAuc ? <p className="tabular"><span className="text-headline font-semibold">{f2(headAuc.value)}</span><span className="ml-2 text-sm text-muted-foreground">{range(headAuc.ci)} · 0.50 is a coin flip</span></p> : <p className="text-sm text-muted-foreground">range not computed</p>}
          {mc && auc(/S4|judge/i) && <p className="text-sm">The single judge before it: <b className="tabular">{f2(auc(/S4|judge/i)!.value)}</b>{range(auc(/S4|judge/i)!.ci)}; the ranges overlap.</p>}
          {auc(/facts/i) && <p className="text-sm">The first method, facts → rules: <b className="tabular">{f2(auc(/facts/i)!.value)}</b>{range(auc(/facts/i)!.ci)}, no better than chance.</p>}
          {ev.judge_eval?.citations_total ? <p className="text-sm text-muted-foreground">{ev.judge_eval.citations_valid} of {ev.judge_eval.citations_total} of the {mc ? "single " : ""}judge&rsquo;s citations were found word for word in the transcript.</p> : null}
        </div>
      </div>

      <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
        <p className="eyebrow">Ladder · 3-fold cross-validation, out-of-fold (dev / Testset_30 / holdout), speech transcripts</p>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>{["Method", "Escalation F1", "Recall", "Precision", "Balanced acc.", "Sent to a person", "False alarms", "AUC [95% range]"].map((h) => <th key={h} className="py-1.5 pr-3 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody className="tabular divide-y divide-border align-top">
            {([...ladder, ...base] as LadderRow[]).map((r, i) => (
              <tr key={r.label} className={`${r.strong ? "font-semibold" : ""} ${r.muted ? "text-muted-foreground" : ""} ${i === ladder.length ? "border-t-2 border-border" : ""}`}>
                <td className="py-2 pr-3">{r.label}{"note" in r && r.note && <span className="block text-xs font-normal text-muted-foreground">{r.note}</span>}</td>
                <td className="py-2 pr-3">{f2(r.f1)}</td><td className="py-2 pr-3">{"r" in r ? f2(r.r) : "–"}</td><td className="py-2 pr-3">{"p" in r ? f2(r.p) : "–"}</td>
                <td className="py-2 pr-3">{"bacc" in r ? f2(r.bacc) : "–"}</td><td className="py-2 pr-3">{"load" in r ? pct0(r.load) : "–"}</td><td className="py-2 pr-3">{"fa" in r && r.fa != null ? r.fa : "–"}</td>
                <td className="py-2">{r.auc ? `${f2(r.auc.value)}${range(r.auc.ci)}` : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-muted-foreground">Below the line: baselines. Flag none scores 0 by definition; flag all and flag none rank no better than a coin (AUC 0.50). &ldquo;–&rdquo;: not measured under this protocol.</p>
      </div>

      <div className="elevated space-y-2 rounded-[var(--radius-panel)] p-6">
        <p className="eyebrow">What we found</p>
        <p className="text-body leading-relaxed">
          Our first method (AI facts scored by fixed rules) <b>ranked calls no better than chance</b>{auc(/facts/i) ? ` (AUC ${f2(auc(/facts/i)!.value)}${range(auc(/facts/i)!.ci)})` : ""}.
          We measured that instead of tuning it away, kept the pre-fix result ({f2(prefix?.overall.escalation.f1.value)} on the unseen holdout) on record, and changed the decision: an AI judge now reads the whole call and cites the passages it relies on, while the facts and rules stay as the explanation.
          It raises {judge?.oof?.false_alarms === 0 ? "no false alarm" : `${judge?.oof?.false_alarms} false alarms`} and ranks calls above chance{auc(/S4|judge/i) ? ` (AUC ${f2(auc(/S4|judge/i)!.value)}${range(auc(/S4|judge/i)!.ci)})` : ""}, but it finds only about {shipped?.oof?.esc_r != null ? `${Math.round(shipped.oof.esc_r * 100)} in 100` : "a quarter of the"} calls that need a person.
          {cond && !ev.methods!.ship_rule_pass ? " A learned recall layer on top did not beat it under cross-validation, so it is not shipped." : ""}
          {mc ? ` Then we split the judge into one check per criterion: still ${mc.false_alarms === 0 ? "no false alarm" : `${mc.false_alarms} false alarms`}, AUC ${f2(mc.auc)}${range(mc.auc_ci)}, and it finds about ${Math.round((mc.esc_r ?? 0) * 100)} in 100 calls that need a person. That is what ships.` : ""}
        </p>
      </div>
    </section>
  );
}
