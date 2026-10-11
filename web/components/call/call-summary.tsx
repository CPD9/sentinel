"use client";
// The top block of every call, identical in the inbox panel and on the call page (Nik's design 04), so the decision,
// its reason and the passage player are always in the same place:
//   header        Alert | Call ID · date · duration
//   why + risk    the plain reason (Review: why the system is unsure) | "Risk 91 · alert line 70"
//   what was said transcript excerpt with the Standard German gloss + the passage player
//   evidence      FACTS first (who said what, quote + gloss, counter-evidence), then how the rule decided (risk vs line,
//                 which methods support it), keywords second, confidence in words
//   counterfactual why not flagged / what would change this
//   act           dismiss · flag · escalate · confirm fraud
// Every sentence is built from the result and the decision trace; when a part is missing it says so.
import { AlertTriangle, ArrowUpRight, Check, Eye, Loader2, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";
import { ExcerptPlayer } from "@/components/inbox/excerpt-player";
import { CRITERION_LABEL, criterionColor } from "@/lib/colors";
import {
  COMPONENT_WORDS, DECISION_LABEL, METHOD_LABEL, blockingFailure, isJudgePath, concerns, factSentence, methods, officerWords, plainReason, score, speakerLabel, stripTemplate, topRule, unsureLine,
} from "@/lib/explain";
import { getJudge, getMethods, snippetUrl } from "@/lib/data";
import { fmtDateTime, fmtTime } from "@/lib/format";

import type { AnalysisArtifact, CallResult, Criterion, Decision, DecisionTrace, Fact, JudgeVerdict, RuleResult, Thresholds, Transcript } from "@/lib/types";
import { useAsync, type Loadable } from "@/lib/use-async";
import { cn } from "@/lib/utils";
import { ActionBar } from "./action-bar";

const DECISION_UI: Record<Decision, { icon: typeof Check; color: string }> = {
  alarm: { icon: OctagonAlert, color: "text-alarm" },
  review: { icon: Eye, color: "text-review" },
  no_alert: { icon: Check, color: "text-noalert" },
};

const duration = (s: number | null | undefined) => (s == null ? null : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);

export function Eyebrow({ children, id }: { children: React.ReactNode; id?: string }) {
  return <h3 id={id} className="eyebrow flex items-center gap-0.5">{children}</h3>;
}

export interface CallMeta { call_id: string; updated_at: string | null; duration_s: number | null; is_mock: boolean }

/** Header row alone (also used while a call is still processing). */
export function CallHeader({ meta, decision, href, pending }: { meta: CallMeta; decision: Decision | null; href?: string; pending?: boolean }) {
  const d = decision && !pending ? DECISION_UI[decision] : null;
  const when = [fmtDateTime(meta.updated_at), duration(meta.duration_s)].filter((x) => x && x !== "–").join(" · ");
  return (
    <header className="flex items-start justify-between gap-3 border-b border-border px-6 py-4">
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
        {d && decision ? (
          <span className={cn("flex items-center gap-2 text-headline font-semibold tracking-tight", d.color)}>
            <d.icon className="size-7" aria-hidden />{DECISION_LABEL[decision]}
          </span>
        ) : (
          <span className="flex items-center gap-2 text-headline font-semibold tracking-tight text-info">
            <Loader2 className="size-7 animate-spin motion-reduce:animate-none" aria-hidden />Processing
          </span>
        )}
        <span aria-hidden className="h-8 w-px bg-border" />
        <h2 className="flex items-baseline gap-2 text-title"><span className="text-muted-foreground">Call ID</span><span className="font-mono">{meta.call_id}</span></h2>
        {when && <span className="text-sm text-muted-foreground">{when}</span>}
      </div>
      {href && (
        <Link href={href} className="inline-flex shrink-0 items-center gap-1 pt-2 text-sm underline-offset-4 hover:underline">
          {pending ? "Watch progress" : "Open full call"}<ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      )}
    </header>
  );
}

export function CallSummary({ meta, result, trace, analysis, transcript, thresholds, href, onCite, compact }: {
  meta: CallMeta; result: CallResult; trace: Loadable<DecisionTrace | null>; analysis: Loadable<AnalysisArtifact | null>;
  transcript: Loadable<Transcript | null>; thresholds: Thresholds | null;
  /** link to the full call page (inbox panel only) */
  href?: string;
  /** a fact or cited line was clicked: the call page scrolls its transcript there and seeks the audio */
  onCite?: (segmentIds: string[]) => void;
  /** inbox panel: fewer facts, details one click away */
  compact?: boolean;
}) {
  const t = trace.data ?? null;
  const judge = useAsync(() => getJudge(result.call_id), `judge:${result.call_id}`).data ?? null;
  const judgePath = isJudgePath(t?.decision_path);
  const th = thresholds ?? t?.thresholds ?? null;
  const decision = result.decision;
  // A failed step is always shown, next to the evidence. It replaces the reason only when it decided the call
  // (decision_path "stage_error"); a failed trigger POST or snippet cut never hides a valid alert, its transcript or passages.
  const errors = result.stage_errors;
  const broken = blockingFailure(errors, t?.decision_path);
  const [focus, setFocus] = useState<{ segs: string[]; n: number } | null>(null);
  const cite = (segs: string[]) => { setFocus((f) => ({ segs, n: (f?.n ?? 0) + 1 })); onCite?.(segs); };

  // Passages for the player: findings at or above the review line; a cleared call shows the passage that was checked.
  const findings = useMemo(() => [...result.findings].sort((a, b) => b.risk - a.risk), [result]);
  const review = th?.review ?? null;
  const passages = useMemo(() => {
    const flagged = review != null ? findings.filter((f) => f.risk >= review) : findings.slice(0, 1);
    const shown = flagged.length || decision !== "no_alert" || !findings[0] ? flagged : [findings[0]];
    return shown.flatMap((f) => f.evidence);
  }, [findings, review, decision]);

  // Facts behind the deciding rules (fired first), then any other valid fact, so "who said what" is always the lead.
  const rules = useMemo(() => (t ? [...t.rules].filter((r) => r.risk > 0).sort((a, b) => Number(b.fired) - Number(a.fired) || b.risk - a.risk) : []), [t]);
  const leadFacts = useMemo(() => {
    if (!t) return [] as Fact[];
    const byId = new Map(t.facts.map((f) => [f.fact_id, f]));
    const ids = [...new Set(rules.flatMap((r) => r.fact_ids))];
    return ids.map((id) => byId.get(id)).filter((f): f is Fact => !!f);
  }, [t, rules]);
  const gloss = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of t?.facts ?? []) if (f.gloss_de && f.segment_ids[0] && !m.has(f.segment_ids[0])) m.set(f.segment_ids[0], f.gloss_de);
    return m;
  }, [t]);
  const factSegments = useMemo(() => [...(judge?.citations ?? []).flatMap((c) => c.segment_ids), ...leadFacts.slice(0, compact ? 3 : 6).flatMap((f) => f.segment_ids)], [leadFacts, compact, judge]);

  const reason = t ? plainReason(t) : null;
  const heading = decision === "alarm" ? "Why this was flagged" : decision === "review" ? "Why a person must look" : "Why it was not flagged";
  const kwHeard = t ? [...new Set(t.keyword_hits.map((h) => h.matched_text))] : [];
  const docsLoading = (transcript.status === "loading" && !transcript.data) || (analysis.status === "loading" && !analysis.data);

  return (
    <div className="space-y-7 px-6 py-5">
      {/* why + risk */}
      <div className="grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-labelledby="why" className="space-y-2">
          <Eyebrow id="why">{heading}</Eyebrow>
          {broken ? (
            <p className="text-lead font-semibold">A processing step failed before the decision, so the call was not fully analysed. A person decides.</p>
          ) : trace.status === "loading" && !t ? <Skeleton className="h-14" /> : !t ? (
            <p className="text-lead font-semibold">{findings[0]?.reason ?? "No decision trace is available for this call."}</p>
          ) : judgePath && judge ? (
            <>
              <p className="text-lead font-semibold leading-snug">
                {judge.decision === "no_alert" ? "The AI judge found no violation." : `${CRITERION_LABEL[judge.criterion as Criterion] ?? judge.criterion}: the AI judge ${judge.decision === "alarm" ? "flags this call" : "asks a person to look"}.`}
              </p>
              <p lang="de" className="text-sm leading-relaxed">“{judge.reason}”</p>
              {decision === "review" && <p className="text-sm font-medium text-review">{unsureLine(t!)}</p>}
            </>
          ) : decision === "no_alert" ? (
            <>
              <p className="text-lead font-semibold leading-snug">
                {rules.length === 0 ? "No fact in this call breaks a rule." : "No check reached the review line."}
              </p>
              {rules.length > 0 && reason && <p className="text-sm">Closest: {reason} (risk {score(rules[0].risk)}).</p>}
              {kwHeard.length > 0 && (
                <p className="text-sm text-muted-foreground">
                  Keywords were heard (<span lang="gsw">{kwHeard.slice(0, 3).map((k) => `“${k}”`).join(", ")}</span>), but a keyword alone never raises an alert.
                </p>
              )}
            </>
          ) : (
            <>
              <p className="text-lead font-semibold leading-snug">{reason ?? "No rule-breaking fact was found."}</p>
              {decision === "review" && <p className="text-sm font-medium text-review">{unsureLine(t)}</p>}
            </>
          )}
          {result.findings[0] && (
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <span aria-hidden className="inline-block size-2 rounded-full" style={{ background: criterionColor(findings[0].criterion) }} />
              Criterion: {CRITERION_LABEL[findings[0].criterion as Criterion] ?? findings[0].criterion}
            </p>
          )}
        </section>
        <RiskBlock risk={broken && findings.length === 0 ? null : result.risk_score} confidence={result.confidence} th={th} decision={decision} trace={t} />
      </div>

      {errors.length > 0 && (
        <div role="alert" className="space-y-1 rounded-lg border border-alarm/40 bg-alarm-bg px-3 py-2 text-sm text-alarm">
          <p className="font-semibold">
            {broken ? "A step failed before the decision:" : `A step after the decision failed. The ${DECISION_LABEL[decision].toLowerCase()}, its evidence and the transcript below are complete.`}
          </p>
          <ul className="space-y-0.5">
            {errors.map((e, i) => (
              <li key={i} className="flex gap-2"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden /><span><code className="font-mono">{e.stage}</code>: {e.message}</span></li>
            ))}
          </ul>
        </div>
      )}

      {/* what was said: always, when there is anything to show (a failed step never hides real evidence) */}
      {(passages.length > 0 || factSegments.length > 0 || !broken) && (
        <section aria-labelledby="said" className="space-y-3 border-t border-border pt-5">
          <Eyebrow id="said">What was said</Eyebrow>
          {passages.length === 0 && factSegments.length === 0 ? (
            <p className="text-sm text-muted-foreground">No passage reached the review line, and no fact supports a rule.</p>
          ) : docsLoading ? (
            <div className="space-y-2" aria-busy="true"><Skeleton className="h-24" /><Skeleton className="h-12" /></div>
          ) : (
            <>
              {decision === "no_alert" && passages.length > 0 && <p className="text-xs text-muted-foreground">Passage checked, below the review line:</p>}
              <ExcerptPlayer callId={result.call_id} passages={passages} transcript={transcript.data ?? null} hits={t?.keyword_hits ?? []}
                waveform={analysis.data?.waveform_peaks ?? null} mock={meta.is_mock} gloss={gloss} factSegments={factSegments} focus={focus} />
            </>
          )}
        </section>
      )}

      {/* evidence: facts first, then the rule, keywords, confidence */}
      {(t || !broken) && (
        <div className="grid gap-x-10 gap-y-6 border-t border-border pt-5 lg:grid-cols-2">
          <section aria-labelledby="facts" className="space-y-3">
            {judge && <JudgeBlock judge={judge} result={result} transcript={transcript.data ?? null} onCite={cite} />}
            <Eyebrow id="facts">{judge ? "Facts behind the rules (the why)" : "Evidence: what the AI found"}<InfoTip term="fact" /></Eyebrow>
            {trace.status === "loading" && !t ? <Skeleton className="h-24" /> : !t ? (
              <p className="text-sm text-muted-foreground">No decision trace, so the extracted facts are not available.</p>
            ) : leadFacts.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No fact supports a rule. {t.facts.length} fact{t.facts.length === 1 ? " was" : "s were"} extracted from the whole call and checked.
              </p>
            ) : (
              <FactList facts={leadFacts} max={compact ? 3 : 6} onCite={cite} />
            )}
          </section>
          <div className="space-y-6">
            {t && rules.length > 0 && <RuleBlock rules={rules.slice(0, compact ? 1 : 3)} t={t} th={th} />}
            <section aria-labelledby="kw" className="space-y-1.5">
              <Eyebrow id="kw">Keywords (second signal)<InfoTip term="keyword_family" /></Eyebrow>
              <Keywords trace={trace} />
            </section>
            <Reliability trace={trace} analysis={analysis} />
          </div>
        </div>
      )}

      {/* how each detection method decided (strategy comparison run) */}
      {t && <MethodStrip callId={result.call_id} decision={decision} compact={compact} />}

      {/* counterfactual */}
      {t && (decision !== "alarm" || t.what_would_change) && (
        <div className="grid gap-4 border-t border-border pt-5 md:grid-cols-2">
          {decision !== "alarm" && <Counterfactual title="Why not flagged" text={t.why_not_flagged ?? stripTemplate(result.narrative).text} template={!t.why_not_flagged} />}
          {t.what_would_change && <Counterfactual title="What would change this" text={t.what_would_change} />}
        </div>
      )}

      <div className={cn("border-t border-border pt-5", compact && "sticky bottom-0 -mx-6 rounded-b-[var(--radius-panel)] bg-card px-6 pb-4")}>
        <ActionBar callId={result.call_id} decision={decision} compact={compact} />
      </div>
      {href && <span className="sr-only"><Link href={href}>Open full call</Link></span>}
    </div>
  );
}

/** "Risk 91 · alert line 70" with one bar; review line as a faint tick; confidence in words. */
function RiskBlock({ risk, confidence, th, decision, trace }: { risk: number | null; confidence: number | null; th: Thresholds | null; decision: Decision; trace: DecisionTrace | null }) {
  const fill = decision === "alarm" ? "var(--gauge-alarm)" : decision === "review" ? "var(--gauge-review)" : "var(--noalert)";
  const below = confidence != null && th != null && confidence < th.confidence_gate;
  const worries = concerns(trace?.confidence_breakdown ?? null).filter((c) => c !== "risk close to a line");
  return (
    <section aria-labelledby="risk" className="space-y-2">
      <Eyebrow id="risk">Risk and alert line<InfoTip term="risk" /></Eyebrow>
      <p className="tabular flex items-baseline gap-3">
        <span className="text-display font-semibold tracking-tight">{risk == null ? "n/a" : <><span className="sr-only">Risk </span>{score(risk)}</>}</span>
        {th && <span className="text-lead text-muted-foreground">· alert line {score(th.alarm)}</span>}
      </p>
      <div className="relative pt-1" role="meter" aria-label="Risk" aria-valuemin={0} aria-valuemax={100} aria-valuenow={risk == null ? undefined : Math.round(risk * 100)}
        aria-valuetext={risk == null ? "not available" : `risk ${score(risk)}, alert line ${th ? score(th.alarm) : "unknown"}`}>
        <div className="relative h-2.5 rounded-full bg-muted">
          {risk != null && <div className="gauge-fill absolute inset-y-0 left-0 rounded-full" style={{ width: `${risk * 100}%`, background: fill }} />}
          {th && <span className="absolute -inset-y-1 w-px bg-muted-foreground/70" style={{ left: `${th.review * 100}%` }} />}
          {th && <span className="absolute -inset-y-1.5 w-0.5 rounded-full bg-foreground" style={{ left: `${th.alarm * 100}%` }} />}
        </div>
        {th && (
          <div className="relative mt-1.5 h-4 text-xs text-muted-foreground">
            <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${th.review * 100}%` }}>review {score(th.review)}</span>
            <span className="absolute -translate-x-1/2 whitespace-nowrap font-semibold text-foreground" style={{ left: `${th.alarm * 100}%` }}>alert {score(th.alarm)}</span>
          </div>
        )}
      </div>
      <p className={cn("flex flex-wrap items-center gap-x-1 pt-2 text-sm", below ? "font-medium text-review" : "text-muted-foreground")}>
        {confidence == null ? "Confidence not computed, so a person decides."
          : below ? `Unsure (confidence ${score(confidence)}, below the gate ${score(th!.confidence_gate)}): a person decides.`
          : decision === "review" ? `Confidence ${score(confidence)}: the evidence is clear; the risk level sends it to a person.`
          : `Sure enough to decide alone (confidence ${score(confidence)}).`}
        {worries.length > 0 && !below && <span>Watch: {worries.join(", ")}.</span>}
        <InfoTip term="confidence" />
      </p>
    </section>
  );
}

function FactList({ facts, max, onCite }: { facts: Fact[]; max: number; onCite: (segs: string[]) => void }) {
  const shown = facts.slice(0, max);
  return (
    <ol className="space-y-2">
      {shown.map((f) => (
        <li key={f.fact_id}>
          <button type="button" onClick={() => onCite(f.segment_ids)} title="Show this passage in the transcript"
            className={cn("w-full rounded-lg border border-border px-3 py-2 text-left transition-colors hover:bg-muted", !f.valid && "border-dashed opacity-70")}>
            <span className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-semibold">{factSentence(f)}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{f.segment_ids.join(", ")}</span>
            </span>
            <span className={cn("mt-1 grid gap-x-4 text-sm", f.gloss_de && "sm:grid-cols-2")}>
              <span lang="gsw">“{f.quote}”</span>
              {f.gloss_de && <span lang="de" className="text-muted-foreground">“{f.gloss_de}”</span>}
            </span>
            {f.counter_evidence && <span className="mt-1 block text-xs text-muted-foreground">Against it: {f.counter_evidence}</span>}
            {!f.valid && <span className="mt-1 block text-xs font-medium text-review">Not verified against the transcript ({f.drop_reason ?? "dropped"}); it does not count.</span>}
          </button>
        </li>
      ))}
      {facts.length > max && <li className="text-xs text-muted-foreground">{facts.length - max} more in Details → Reasoning.</li>}
    </ol>
  );
}

/** Which rule decided, its risk against the line, which methods support it and what lowered it. */
function RuleBlock({ rules, t, th }: { rules: RuleResult[]; t: DecisionTrace; th: Thresholds | null }) {
  const byId = new Map(t.facts.map((f) => [f.fact_id, f]));
  return (
    <section aria-labelledby="rule" className="space-y-2">
      <Eyebrow id="rule">How it was decided<InfoTip term="rule" /></Eyebrow>
      <ul className="space-y-3">
        {rules.map((r) => {
          const m = methods(r, t);
          const counterIds = /counter-evidence ((?:f\d+(?:,\s*)?)+)/.exec(r.reason)?.[1].split(/,\s*/) ?? [];
          const counter = counterIds.map((id) => byId.get(id)).filter((f): f is Fact => !!f);
          return (
            <li key={r.criterion} className="space-y-1 text-sm">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-semibold">{CRITERION_LABEL[r.criterion] ?? r.criterion}</span>
                <span className={r.fired ? "text-foreground" : "text-muted-foreground"}>{r.fired ? "rule fired" : "rule did not fire"}</span>
                <span className="tabular text-muted-foreground">· risk {score(r.risk)}{th ? ` vs alert line ${score(th.alarm)}` : ""}</span>
              </p>
              <p className="text-muted-foreground">
                Methods: AI facts {m.facts > 0 ? `✓ (${m.facts})` : "–"} · keywords {m.keywords > 0 ? `✓ (${m.keywords})` : "–"}
                {" — "}{m.agree ? "both methods agree." : m.factsOnly ? "found by the AI facts; no keyword in the same place." : m.keywordsOnly ? "keywords only; no fact backs it, so it cannot alert." : "no supporting input."}
              </p>
              {counter.length > 0 && (
                <p className="text-muted-foreground">Lowered by counter-evidence: {counter.map((f) => <span key={f.fact_id} lang="gsw">“{f.quote}” ({speakerLabel(f.speaker)}) </span>)}</p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Keywords({ trace }: { trace: Loadable<DecisionTrace | null> }) {
  if (trace.status === "loading" && !trace.data) return <Skeleton className="h-5 w-32" />;
  if (!trace.data) return <p className="text-sm text-muted-foreground">not available</p>;
  const counts = [...trace.data.keyword_hits.reduce((m, h) => m.set(h.matched_text, (m.get(h.matched_text) ?? 0) + 1), new Map<string, number>())].sort((a, b) => b[1] - a[1]);
  if (counts.length === 0) return <p className="text-sm text-muted-foreground">None heard.</p>;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-0.5 text-sm">
      {counts.map(([term, n]) => <li key={term}><span lang="gsw">“{term}”</span><span className="tabular text-muted-foreground"> ×{n}</span></li>)}
    </ul>
  );
}

/** Confidence in words: one line per component of the trace, plus the call's audio quality. */
function Reliability({ trace, analysis }: { trace: Loadable<DecisionTrace | null>; analysis: Loadable<AnalysisArtifact | null> }) {
  const comps = trace.data?.confidence_breakdown?.components ?? null;
  const loading = trace.status === "loading" && !trace.data;
  const order = ["asr", "audio_quality", "missing_evidence", "conflicts", "threshold_proximity"];
  const snr = analysis.data?.audio_quality?.call_snr_db;
  return (
    <section aria-labelledby="rel" className="space-y-1.5">
      <Eyebrow id="rel">Confidence, in words<InfoTip term="confidence" /></Eyebrow>
      {loading ? <Skeleton className="h-16 w-64" /> : !comps ? (
        <p className="text-sm text-muted-foreground">Confidence was not computed for this call.</p>
      ) : (
        <dl className="grid grid-cols-[minmax(0,13rem)_1fr] gap-x-4 gap-y-1 text-sm">
          {order.filter((k) => k in comps).map((k) => {
            const w = COMPONENT_WORDS[k];
            const v = comps[k];
            const low = v < 0.7;
            return (
              <div key={k} className="contents">
                <dt className="text-muted-foreground" title={w?.help}>{w?.label ?? k}</dt>
                <dd className={cn(low && "font-medium text-review")}>
                  {low ? w?.low : w?.ok} <span className="tabular text-muted-foreground">({score(v)}{k === "audio_quality" && snr != null ? `, SNR ${snr.toFixed(0)} dB` : ""})</span>
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}

function Counterfactual({ title, text, template }: { title: string; text: string | null; template?: boolean }) {
  return (
    <section className="space-y-1.5 rounded-xl bg-muted/60 p-4">
      <Eyebrow>{title}</Eyebrow>
      {text ? <p className="text-sm leading-relaxed">{officerWords(text)}</p> : <p className="text-sm text-muted-foreground">Not available for this call.</p>}
      {template && text && <p className="text-[11px] text-muted-foreground">Template text (no LLM narrative in this run).</p>}
    </section>
  );
}

/** "How each method decided": the five strategies of the comparison run on this call. Agreement is stated; any
 *  disagreement is styled like a review (amber), because that is what it means for the officer. Missing → nothing. */
function MethodStrip({ callId, decision, compact }: { callId: string; decision: Decision; compact?: boolean }) {
  const m = useAsync(() => getMethods(callId), `methods:${callId}`);
  if (!m.data) return null;
  const rows = ["S1", "S2", "S3", "S4", "S8"].map((id) => m.data!.methods.find((x) => x.id === id)).filter((x): x is NonNullable<typeof x> => !!x && x.decision != null);
  const differ = rows.filter((r) => r.decision !== decision);
  const shipped = rows.find((r) => r.id === "S3");
  const color = (d: Decision | null) => (d === "alarm" ? "text-alarm" : d === "review" ? "text-review" : "text-noalert");
  return (
    <section aria-labelledby="methods" className="space-y-3 border-t border-border pt-5">
      <Eyebrow id="methods">How each method decided</Eyebrow>
      <p className={cn("text-sm", differ.length ? "font-medium text-review" : "text-muted-foreground")}>
        {differ.length === 0 ? `All ${rows.length} methods agree: ${DECISION_LABEL[decision]}.`
          : `Methods disagree: ${differ.map((r) => `${METHOD_LABEL[r.id]?.name ?? r.id} says ${DECISION_LABEL[r.decision!]}`).join(", ")}. A person should double-check.`}
        {shipped && shipped.decision !== decision && <span className="text-muted-foreground"> (The comparison run is older than this result.)</span>}
      </p>
      <ol className={cn("grid gap-2", compact ? "grid-cols-5" : "sm:grid-cols-5")}>
        {rows.map((r) => {
          const off = r.decision !== decision;
          return (
            <li key={r.id} title={`${METHOD_LABEL[r.id]?.how ?? ""}${r.reason ? ` — ${r.reason}` : ""}`}
              className={cn("min-w-0 rounded-lg border px-3 py-2", off ? "border-dashed border-review bg-review-bg/40" : "border-border", r.id === "S3" && "ring-1 ring-foreground/40")}>
              <p className="truncate text-xs text-muted-foreground">{METHOD_LABEL[r.id]?.name ?? r.id}</p>
              <p className={cn("text-sm font-semibold", color(r.decision))}>{DECISION_LABEL[r.decision!]}{r.risk != null && r.risk > 0 && r.decision !== "no_alert" && <span className="tabular font-normal text-muted-foreground"> · {score(r.risk)}</span>}</p>
              {!compact && r.reason && <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{officerWords(r.reason)}</p>}
            </li>
          );
        })}
      </ol>
      <p className="text-[11px] text-muted-foreground">From the strategy comparison run on the same calls; the shipped decision is the hybrid (outlined).</p>
    </section>
  );
}

/** The AI judge's verdict and the passages it cites: quote → segment → time → snippet. Citations it could not ground
 *  in the transcript are marked, never hidden. */
function JudgeBlock({ judge, result, transcript, onCite }: { judge: JudgeVerdict; result: CallResult; transcript: Transcript | null; onCite: (segs: string[]) => void }) {
  const seg = new Map((transcript?.segments ?? []).map((x) => [x.id, x]));
  const snippetOf = new Map<string, string>();
  for (const f of result.findings) for (const e of f.evidence) if (e.snippet_path) for (const id of e.segment_ids) if (!snippetOf.has(id)) snippetOf.set(id, e.snippet_path);
  const tone = judge.decision === "alarm" ? "text-alarm" : judge.decision === "review" ? "text-review" : "text-noalert";
  return (
    <div className="space-y-2 rounded-xl border border-border p-4">
      <p className="eyebrow flex flex-wrap items-center gap-2">Evidence: what the AI judge cited
        <span className={cn("normal-case tracking-normal", tone)}>· verdict {DECISION_LABEL[judge.decision]}{judge.risk > 0 ? `, risk ${score(judge.risk)}` : ""}</span></p>
      {judge.citations.length === 0 ? <p className="text-sm text-muted-foreground">The judge cited no passage{judge.decision === "no_alert" ? " (nothing to flag)" : ""}.</p> : (
        <ol className="space-y-1.5">
          {judge.citations.map((c) => {
            const s0 = c.segment_ids.map((i) => seg.get(i)).find(Boolean);
            const sn = c.segment_ids.map((i) => snippetOf.get(i)).find(Boolean) ?? null;
            const url = sn ? snippetUrl(result.call_id, sn) : null;
            return (
              <li key={c.fact_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
                <button type="button" onClick={() => onCite(c.segment_ids)} className="min-w-0 flex-1 text-left hover:underline" title="Show this passage in the transcript">
                  <span lang="de">“{c.quote}”</span>{!c.valid && <span className="ml-2 text-xs font-medium text-review">not found in the transcript</span>}
                </button>
                <span className="tabular font-mono text-[11px] text-muted-foreground">{c.segment_ids.join(", ")} · {s0?.start_s != null ? fmtTime(s0.start_s) : "–"}</span>
                {url && <a href={url} className="text-xs underline underline-offset-2">passage ±10 s</a>}
              </li>
            );
          })}
        </ol>
      )}
      {judge.version && <p className="font-mono text-[11px] text-muted-foreground">{judge.version}</p>}
    </div>
  );
}
