"use client";
import { ArrowDown, Check, X } from "lucide-react";
import { CriterionChip, SpeakerChip } from "@/components/shell/badges";
import { ScoreBar } from "@/components/shell/score";
import { DocGate } from "@/components/shell/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { criterionColor } from "@/lib/colors";
import { DECISION_LABEL } from "@/lib/explain";
import { humanize, pct } from "@/lib/format";
import type { CallResult, DecisionPath, DecisionTrace } from "@/lib/types";
import type { Loadable } from "@/lib/use-async";
import { cn } from "@/lib/utils";

// decide.py priority order (CLAUDE.md step 8).
const PATH_STEPS: { id: DecisionPath[]; label: string; gives: string }[] = [
  { id: ["stage_error", "missing_evidence", "contradictory_evidence", "low_confidence"], label: "1 · Failed stage, missing or contradictory evidence, or confidence below the gate", gives: "review" },
  { id: ["alarm"], label: "2 · Validated evidence and a rule hit at or above the alert line", gives: "alert" },
  { id: ["review_band"], label: "3 · Risk inside the review band", gives: "review" },
  { id: ["no_alert"], label: "4 · Otherwise", gives: "no alert" },
  { id: ["judge_alarm", "judge_review", "judge_no_alert"], label: "AI judge decides (decision source “direct judge”): its verdict, with its cited passages; facts and rules stay as the why", gives: "the judge's verdict" },
];

export function ReasoningTab({ result, trace }: { result: CallResult; trace: Loadable<DecisionTrace> }) {
  return (
    <DocGate state={trace} unavailable="No decision trace for this call (e.g. a baseline run).">
      {(t) => <Body t={t} result={result} />}
    </DocGate>
  );
}

function Body({ t, result }: { t: DecisionTrace; result: CallResult }) {
  const facts = new Map(t.facts.map((f) => [f.fact_id, f]));
  const hits = new Map(t.keyword_hits.map((h) => [h.hit_id, h]));
  const droppedN = t.facts.filter((f) => !f.valid).length;
  const markers = [{ at: t.thresholds.review, label: "review" }, { at: t.thresholds.alarm, label: "alarm" }];

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">Read top to bottom: facts → rules → confidence → decision. Only the LLM step reads the conversation; everything below it is fixed rules.</p>

      <Step title="1 · Facts" subtitle="Extracted by the LLM, then checked against the transcript by the evidence validator.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr>{["ID", "Speaker", "Act", "Info type", "Quote", "Segments", "Flags"].map((h) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-border">
              {t.facts.map((f) => (
                <tr key={f.fact_id} className={cn(!f.valid && "bg-muted/60 text-muted-foreground")}>
                  <td className="px-2 py-2 font-mono text-xs">{f.fact_id}</td>
                  <td className="px-2 py-2"><SpeakerChip speaker={f.speaker} /></td>
                  <td className="px-2 py-2">{f.act}</td><td className="px-2 py-2">{humanize(f.info_type)}</td>
                  <td className="px-2 py-2">
                    <span lang="gsw" className={cn(!f.valid && "line-through")}>“{f.quote}”</span>
                    {!f.valid && <p className="mt-1 text-xs text-alarm">dropped: {f.drop_reason} — raises “missing evidence”</p>}
                    {f.counter_evidence && <p className="mt-1 text-xs text-muted-foreground">counter: {f.counter_evidence}</p>}
                  </td>
                  <td className="px-2 py-2 font-mono text-xs">{f.segment_ids.join(", ")}</td>
                  <td className="px-2 py-2 text-xs">{f.recipient_third_party && "third party "}{f.secrecy_cue && "secrecy cue"}{!f.recipient_third_party && !f.secrecy_cue && "–"}</td>
                </tr>
              ))}
              {t.facts.length === 0 && <tr><td colSpan={7} className="px-2 py-4 text-center text-muted-foreground">No facts were extracted.</td></tr>}
            </tbody>
          </table>
        </div>
        {droppedN > 0 && <p className="mt-2 text-xs text-muted-foreground">{droppedN} fact{droppedN > 1 ? "s" : ""} dropped by the validator.</p>}

        <h4 className="mb-1 mt-4 text-xs font-semibold text-muted-foreground">Keyword hits (deterministic; not shown to the LLM)</h4>
        {t.keyword_hits.length === 0 ? <p className="text-sm text-muted-foreground">No keyword hits.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr>{["ID", "Family", "Term → matched text", "Segment", "Score"].map((h) => <th key={h} className="px-2 py-1 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-border">{t.keyword_hits.map((h) => (
              <tr key={h.hit_id}><td className="px-2 py-1.5 font-mono text-xs">{h.hit_id}</td><td className="px-2 py-1.5">{h.family}</td>
                <td className="px-2 py-1.5">{h.term} → <b>{h.matched_text}</b></td><td className="px-2 py-1.5 font-mono text-xs">{h.segment_id}</td><td className="tabular px-2 py-1.5">{h.score.toFixed(2)}</td></tr>
            ))}</tbody>
          </table>
        )}
      </Step>
      <Arrow />
      <Step title="2 · Rules" subtitle={`One rule per criterion. Markers: review ${pct(t.thresholds.review)}, alarm ${pct(t.thresholds.alarm)}.`}>
        <ul className="space-y-3">
          {[...t.rules].sort((a, b) => b.risk - a.risk).map((r) => (
            <li key={r.criterion} className="grid gap-x-4 gap-y-1 md:grid-cols-[14rem_6rem_12rem_1fr] md:items-center">
              <CriterionChip criterion={r.criterion} />
              <span className={cn("w-fit rounded border px-2 py-0.5 text-xs font-medium", r.fired ? "border-foreground" : "border-border text-muted-foreground")}>{r.fired ? <><Check className="mr-1 inline size-3" />fired</> : <><X className="mr-1 inline size-3" />not fired</>}</span>
              <div className="flex items-center gap-2"><ScoreBar value={r.risk} color={criterionColor(r.criterion)} markers={markers} label={`${r.criterion} risk`} /><span className="tabular w-10 text-right text-xs">{pct(r.risk)}</span></div>
              <div className="text-xs text-muted-foreground">{r.reason}
                {(r.fact_ids.length > 0 || r.keyword_hit_ids.length > 0) && <span className="ml-1 font-mono">[inputs: {[...r.fact_ids.filter((x) => facts.has(x)), ...r.keyword_hit_ids.filter((x) => hits.has(x))].join(", ")}]</span>}
              </div>
            </li>
          ))}
        </ul>
      </Step>
      <Arrow />
      <Step title="3 · Confidence" subtitle="1 = no concern. The call needs total confidence at or above the gate to be a confident alert or no-alert.">
        {t.confidence_breakdown ? (
          <div className="space-y-2">
            {Object.entries(t.confidence_breakdown.components).map(([k, v]) => (
              <div key={k} className="grid grid-cols-[11rem_1fr_3rem] items-center gap-3 text-sm"><span>{humanize(k)}</span><ScoreBar value={v} label={k} /><span className="tabular text-right text-xs">{pct(v)}</span></div>
            ))}
            <div className="grid grid-cols-[11rem_1fr_3rem] items-center gap-3 border-t border-border pt-2 text-sm font-semibold">
              <span>total (gate {pct(t.confidence_breakdown.gate)})</span>
              <ScoreBar value={t.confidence_breakdown.value} markers={[{ at: t.confidence_breakdown.gate, label: "gate" }]} color={t.confidence_breakdown.value >= t.confidence_breakdown.gate ? "var(--ok)" : "var(--review)"} label="total confidence" />
              <span className="tabular text-right text-xs">{pct(t.confidence_breakdown.value)}</span>
            </div>
          </div>
        ) : <p className="text-sm text-muted-foreground">Confidence was not computed for this call (n/a).</p>}
      </Step>
      <Arrow />
      <Step title="4 · Decision path" subtitle="Checked in this order; the first step that applies decides. Doubt is checked before alert.">
        <ol className="space-y-1.5">
          {PATH_STEPS.map((s) => {
            const hit = s.id.includes(t.decision_path);
            return (
              <li key={s.label} className={cn("rounded-md border px-3 py-2 text-sm", hit ? "border-foreground bg-muted font-semibold" : "border-border text-muted-foreground")}>
                {s.label} → <b>{s.gives}</b>{hit && s.id.length > 1 && <span className="ml-2 font-mono text-xs">({t.decision_path})</span>}
                {hit && <span className="ml-2 text-xs">← this call</span>}
              </li>
            );
          })}
        </ol>
        <p className="mt-2 text-sm">Result: <b>{DECISION_LABEL[result.decision]}</b> (risk {pct(t.risk_score)}, confidence {pct(t.confidence)}).</p>
        {(t.why_not_flagged || t.what_would_change) && (
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {t.why_not_flagged && <div className="rounded-md bg-muted p-3 text-sm"><b>Why not flagged.</b> {t.why_not_flagged}</div>}
            {t.what_would_change && <div className="rounded-md bg-muted p-3 text-sm"><b>What would change this.</b> {t.what_would_change}</div>}
          </div>
        )}
      </Step>
    </div>
  );
}

function Step({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <Card><CardHeader><div><CardTitle>{title}</CardTitle><CardDescription>{subtitle}</CardDescription></div></CardHeader><CardContent>{children}</CardContent></Card>
  );
}
const Arrow = () => <div className="flex justify-center text-muted-foreground" aria-hidden><ArrowDown className="size-4" /></div>;
