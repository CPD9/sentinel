"use client";
// Right panel of the Overview (layout after Jules's wireframe): everything an officer needs to judge one call.
//   header        decision │ call id · date, "Open full call" button, close ✕ (also Esc; the Overview then shows a placeholder)
//   what was said transcript excerpt around the cited passages + one player with the waveform (excerpt-player.tsx)
//   two columns   risk and threshold + why | evidence (keywords) + reliability
//   (actions)     the verdict buttons come in step 2b
// Data: the list row, GET /calls/{id} (reason, passages), /trace (keywords, why review / not flagged, transcript
// certainty), /analysis (waveform, audio quality), /transcript (context lines). Trace, analysis and transcript may be
// missing (404, e.g. a call whose ASR failed): their parts then say "not available" instead of breaking.
import { AlertTriangle, Check, Eye, Loader2, OctagonAlert, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ActionLink } from "@/components/ui/action-link";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";
import { CRITERION_LABEL } from "@/lib/colors";
import { getAnalysis, getCall, getTrace, getTranscript } from "@/lib/data";
import { fmtDateTime, pct } from "@/lib/format";
import type { AnalysisArtifact, CallListItem, CallResult, Decision, DecisionPath, DecisionTrace, Finding, Thresholds, Transcript } from "@/lib/types";
import { useAsync, type Loadable } from "@/lib/use-async";
import { cn } from "@/lib/utils";
import { ExcerptPlayer } from "./excerpt-player";

/** Why a call went to review, in plain words (decide.py priority order, CLAUDE.md step 8). */
const WHY_REVIEW: Partial<Record<DecisionPath, string>> = {
  stage_error: "A processing step failed, so the call was not fully analysed.",
  missing_evidence: "Some cited evidence could not be verified against the transcript.",
  contradictory_evidence: "The evidence points both ways.",
  low_confidence: "Confidence is below the gate, for example because of unclear audio or transcript.",
  review_band: "The risk sits between the review and the alarm threshold.",
};

const DECISION_UI: Record<Decision, { label: string; icon: typeof Check; color: string }> = {
  alarm: { label: "Alarm", icon: OctagonAlert, color: "text-alarm" },
  review: { label: "Review", icon: Eye, color: "text-review" },
  no_alert: { label: "No alert", icon: Check, color: "text-noalert" },
};

const duration = (s: number | null) => (s == null ? "–" : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);

/** Small uppercase section label, as in the wireframe. */
function Label({ children, className }: { children: React.ReactNode; className?: string }) {
  return <h3 className={cn("flex items-center gap-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground", className)}>{children}</h3>;
}

export function CallPanel({ item, thresholds }: { item: CallListItem; thresholds: Thresholds | null }) {
  const id = item.call_id;
  const version = item.updated_at ?? "";                    // a re-run (new updated_at) reloads the panel
  const pending = item.status === "queued" || item.status === "processing";
  const detail = useAsync(() => (pending ? Promise.resolve(null) : getCall(id)), `panel:${id}:${version}:${pending}`);
  const trace = useAsync<DecisionTrace | null>(() => (pending ? Promise.resolve(null) : getTrace(id)), `panel-trace:${id}:${version}`);
  const analysis = useAsync<AnalysisArtifact | null>(() => (pending ? Promise.resolve(null) : getAnalysis(id)), `panel-an:${id}:${version}`);
  const transcript = useAsync<Transcript | null>(() => (pending ? Promise.resolve(null) : getTranscript(id)), `panel-tr:${id}:${version}`);
  const result: CallResult | null = detail.data?.kind === "result" ? detail.data.data : null;
  const th = thresholds ?? trace.data?.thresholds ?? null;
  const d = item.decision && !pending ? DECISION_UI[item.decision] : null;
  const router = useRouter();

  // Esc closes the panel (`?call=` with an empty id = no call open), unless something else already used the key.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !e.defaultPrevented) router.replace("/?call=", { scroll: false }); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <article aria-labelledby="panel-title" className="panel-in elevated rounded-2xl lg:min-h-full">
      {/* header: decision │ call id · date */}
      <header className="flex items-start justify-between gap-3 border-b border-border px-6 py-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          {d ? (
            <span className={cn("flex items-center gap-2 text-xl font-semibold tracking-tight", d.color)}>
              <d.icon className="size-5" aria-hidden />{d.label}
            </span>
          ) : (
            <span className="flex items-center gap-2 text-xl font-semibold tracking-tight text-info">
              <Loader2 className="size-5 animate-spin motion-reduce:animate-none" aria-hidden />Processing
            </span>
          )}
          <span aria-hidden className="h-6 w-px bg-border" />
          <h2 id="panel-title" className="font-mono text-lg">{id}</h2>
          <span className="text-sm text-muted-foreground">{fmtDateTime(item.updated_at)} · {duration(item.duration_s)}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <ActionLink href={pending ? `/calls/${id}/processing` : `/calls/${id}`}>{pending ? "Watch progress" : "Open full call"}</ActionLink>
          <Link href="/?call=" replace scroll={false} aria-label="Close this call" title="Close (Esc)"
            className="group inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
            <X className="size-4 transition-transform duration-200 group-hover:rotate-90 motion-reduce:transition-none" aria-hidden />
          </Link>
        </div>
      </header>

      <div className="space-y-6 px-6 py-5">
        {pending ? (
          <p className="text-sm text-muted-foreground">Still being transcribed and checked. The decision appears here by itself when it is done.</p>
        ) : detail.status === "loading" && !detail.data ? (
          <div className="space-y-3" aria-busy="true"><Skeleton className="h-24" /><Skeleton className="h-12" /><Skeleton className="h-32" /></div>
        ) : detail.status === "error" && !detail.data ? (
          <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            The details of this call could not be loaded ({detail.error.message}).
            <button type="button" onClick={detail.reload} className="inline-flex items-center gap-1 text-link underline-offset-2 hover:underline"><RefreshCw className="size-3" aria-hidden />Retry</button>
          </p>
        ) : result ? (
          <Body item={item} result={result} trace={trace} analysis={analysis} transcript={transcript} th={th} />
        ) : null}
      </div>
    </article>
  );
}

function Body({ item, result, trace, analysis, transcript, th }: {
  item: CallListItem; result: CallResult; trace: Loadable<DecisionTrace | null>; analysis: Loadable<AnalysisArtifact | null>;
  transcript: Loadable<Transcript | null>; th: Thresholds | null;
}) {
  const findings = [...result.findings].sort((a, b) => b.risk - a.risk);
  const top = findings[0] ?? null;
  const decision = result.decision;
  const broken = result.stage_errors.length > 0;
  // what to show as proof: findings at or above the review threshold; a cleared call shows what was checked
  const flagged = th ? findings.filter((f) => f.risk >= th.review) : findings.slice(0, 1);
  const shown: Finding[] = flagged.length || decision !== "no_alert" || !top ? flagged : [top];
  const passages = shown.flatMap((f) => f.evidence);

  const heading = decision === "alarm" ? "Why this was flagged" : decision === "review" ? "Why a person must look" : "Why it was not flagged";
  const why = broken ? WHY_REVIEW.stage_error
    : decision === "no_alert" ? (trace.data?.why_not_flagged ?? result.narrative ?? null)
    : top?.reason ?? result.narrative ?? null;
  const unsure = decision === "review" && !broken && trace.data
    ? `${WHY_REVIEW[trace.data.decision_path] ?? "The system is not sure enough to decide alone."}${trace.data.what_would_change ? ` ${trace.data.what_would_change}` : ""}`
    : null;
  const fraud = shown[0]?.criterion ?? item.criteria[0] ?? null;
  const docsLoading = (transcript.status === "loading" && !transcript.data) || (analysis.status === "loading" && !analysis.data);

  return (
    <>
      {/* what was said */}
      <section aria-labelledby="said" className="space-y-3">
        <h3 id="said" className="sr-only">What was said</h3>
        {broken ? (
          <ul className="space-y-1 rounded-lg border border-alarm/40 bg-alarm-bg px-3 py-2 text-sm text-alarm">
            {result.stage_errors.map((e, i) => (
              <li key={i} className="flex gap-2"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden /><span><code className="font-mono">{e.stage}</code>: {e.message}</span></li>
            ))}
            <li className="pt-1 text-xs">No transcript or audio passages are available for this call.</li>
          </ul>
        ) : passages.length === 0 ? (
          <p className="text-sm text-muted-foreground">No passage reached the review threshold.</p>
        ) : docsLoading ? (
          <div className="space-y-2" aria-busy="true"><Skeleton className="h-24" /><Skeleton className="h-12" /></div>
        ) : (
          <>
            {decision === "no_alert" && <p className="text-xs text-muted-foreground">Passage checked, below the review threshold:</p>}
            <ExcerptPlayer callId={result.call_id} passages={passages} transcript={transcript.data ?? null}
              hits={trace.data?.keyword_hits ?? []} waveform={analysis.data?.waveform_peaks ?? null} mock={item.is_mock} />
          </>
        )}
      </section>

      {/* two columns: risk + why | evidence + reliability */}
      <div className="grid gap-x-10 gap-y-6 border-t border-border pt-5 md:grid-cols-2">
        <div className="space-y-6">
          <RiskBlock risk={broken && findings.length === 0 ? null : result.risk_score} confidence={result.confidence} th={th} decision={decision} />
          <section aria-labelledby="why" className="space-y-1.5">
            <Label><span id="why">{heading}</span></Label>
            {why && <p className="text-[15px] font-medium leading-snug">{why}</p>}
            {unsure && <p className="text-sm leading-relaxed text-muted-foreground">{unsure}</p>}
          </section>
        </div>
        <div className="space-y-6">
          <section aria-labelledby="evidence" className="space-y-2">
            <Label><span id="evidence">Evidence</span></Label>
            <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1.5 text-sm">
              {fraud && !broken && (<><dt className="font-medium">Kind of fraud</dt><dd>{CRITERION_LABEL[fraud] ?? fraud}</dd></>)}
              <dt className="flex items-center gap-0.5 font-medium">Keywords<InfoTip term="keyword_family" /></dt>
              <dd><Keywords trace={trace} /></dd>
            </dl>
          </section>
          <Reliability trace={trace} analysis={analysis} />
        </div>
      </div>
    </>
  );
}

/** Big risk number + one bar with the alarm threshold marked (review threshold as a faint tick); confidence as one line. */
function RiskBlock({ risk, confidence, th, decision }: { risk: number | null; confidence: number | null; th: Thresholds | null; decision: Decision }) {
  const fill = decision === "alarm" ? "var(--gauge-alarm)" : decision === "review" ? "var(--gauge-review)" : "var(--noalert)";
  const below = confidence != null && th != null && confidence < th.confidence_gate;
  return (
    <section aria-labelledby="risk" className="space-y-2">
      <Label><span id="risk">Risk and threshold</span><InfoTip term="risk" /></Label>
      <p className="tabular text-4xl font-semibold tracking-tight">{risk == null ? "n/a" : `${Math.round(risk * 100)}%`}</p>
      <div className="relative pt-1" role="meter" aria-label="Risk" aria-valuemin={0} aria-valuemax={1} aria-valuenow={risk ?? undefined}
        aria-valuetext={risk == null ? "not available" : `${pct(risk)}, alarm threshold ${th ? pct(th.alarm) : "unknown"}`}>
        <div className="relative h-2.5 rounded-full bg-muted">
          {risk != null && <div className="gauge-fill absolute inset-y-0 left-0 rounded-full" style={{ width: `${risk * 100}%`, background: fill }} />}
          {th && <span className="absolute -inset-y-1 w-px bg-muted-foreground/50" style={{ left: `${th.review * 100}%` }} title={`Review threshold ${pct(th.review)}`} />}
          {th && <span className="absolute -inset-y-1.5 w-0.5 rounded-full bg-foreground" style={{ left: `${th.alarm * 100}%` }} />}
        </div>
        {th && (
          <div className="relative mt-1.5 h-4 text-xs">
            <span className="absolute -translate-x-1/2 whitespace-nowrap font-medium" style={{ left: `${th.alarm * 100}%` }}>Alarm threshold {Math.round(th.alarm * 100)}%</span>
          </div>
        )}
      </div>
      <p className={cn("flex items-center gap-0.5 pt-1 text-sm", below ? "text-review" : "text-muted-foreground")}>
        Confidence {confidence == null ? "n/a (not computed)" : `${Math.round(confidence * 100)}%`}
        {confidence != null && th && (below ? " · below the gate, a person decides" : " · above the gate")}
        <InfoTip term="confidence" />
      </p>
    </section>
  );
}

function Keywords({ trace }: { trace: Loadable<DecisionTrace | null> }) {
  if (trace.status === "loading" && !trace.data) return <Skeleton className="h-5 w-32" />;
  if (!trace.data) return <span className="text-muted-foreground">not available</span>;
  const counts = [...trace.data.keyword_hits.reduce((m, h) => m.set(h.term, (m.get(h.term) ?? 0) + 1), new Map<string, number>())].sort((a, b) => b[1] - a[1]);
  if (counts.length === 0) return <span className="text-muted-foreground">none</span>;
  return (
    <ul className="space-y-0.5">
      {counts.map(([term, n]) => <li key={term}><span lang="gsw">“{term}”</span><span className="tabular text-muted-foreground"> ×{n}</span></li>)}
    </ul>
  );
}

// Plain words for the two 0–1 reliability signals. The cut-offs are a display choice of this page, not pipeline thresholds.
const level = (x: number, words: [string, string, string]) => (x >= 0.7 ? words[0] : x >= 0.4 ? words[1] : words[2]);

function Reliability({ trace, analysis }: { trace: Loadable<DecisionTrace | null>; analysis: Loadable<AnalysisArtifact | null> }) {
  const audio = analysis.data?.audio_quality?.call_score ?? null;
  const asr = trace.data?.confidence_breakdown?.components.asr ?? null;
  const loading = (trace.status === "loading" && !trace.data) || (analysis.status === "loading" && !analysis.data);
  const rows: [string, number | null, [string, string, string], string][] = [
    ["Call quality", audio, ["Clear", "Some noise", "Noisy"], "Signal-to-noise of the recording."],
    ["Transcript", asr, ["Certain", "Fairly certain", "Uncertain"], "How sure speech recognition is on the cited passages."],
  ];
  return (
    <section aria-labelledby="rel" className="space-y-2">
      <Label><span id="rel">Reliability</span></Label>
      {loading ? <Skeleton className="h-10 w-48" /> : (
        <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1.5 text-sm">
          {rows.map(([label, v, words, hint]) => (
            <div key={label} className="contents">
              <dt className="font-medium" title={hint}>{label}</dt>
              <dd>{v == null ? <span className="text-muted-foreground">not available</span>
                : <>{level(v, words)} <span className="tabular text-muted-foreground">({Math.round(v * 100)}%)</span></>}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
