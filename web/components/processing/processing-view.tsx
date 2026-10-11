"use client";
// Step timeline, driven by ProcessingEvents (live SSE, or a replay of the recorded run in the local-run fallback). Each
// finished step says what it produced, counted from the call's own documents.
import { AlertTriangle, ArrowRight, Check, Circle, CircleDashed, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useReducer, useState } from "react";
import { Button } from "@/components/ui/button";
import { DecisionBadge } from "@/components/shell/badges";
import { EmptyState } from "@/components/shell/states";
import { getAnalysis, getCall, getTrace, getTranscript, isFixtures, isLocalRun, subscribeCallEvents, type StreamStatus } from "@/lib/data";
import { CRITERION_LABEL } from "@/lib/colors";
import { DECISION_LABEL, TEMPLATE_PREFIX } from "@/lib/explain";
import { useAsync } from "@/lib/use-async";
import { fmtSeconds } from "@/lib/format";
import type { AnalysisArtifact, CallResult, Decision, DecisionTrace, ProcessingEvent, Stage, Transcript } from "@/lib/types";
import { STAGES } from "@/lib/types";
import { cn } from "@/lib/utils";

type StageState = { state: "waiting" | "running" | "done" | "failed"; elapsed?: number | null; cached?: boolean | null; message?: string | null; startedAt?: number };
interface Model { stages: Record<string, StageState>; log: ProcessingEvent[]; decision: Decision | null; finished: boolean }

const init = (): Model => ({ stages: Object.fromEntries(STAGES.map((s) => [s, { state: "waiting" as const }])), log: [], decision: null, finished: false });

function reduce(m: Model, e: ProcessingEvent | "reset"): Model {
  if (e === "reset") return init();
  if (m.log.some((x) => x.seq === e.seq)) return m; // replay after reconnect
  const next: Model = { ...m, log: [...m.log, e], stages: { ...m.stages } };
  if (e.stage) {
    const prev = m.stages[e.stage] ?? { state: "waiting" };
    if (e.event === "stage_started") next.stages[e.stage] = { state: "running", startedAt: Date.now() };
    if (e.event === "stage_finished") next.stages[e.stage] = { ...prev, state: "done", elapsed: e.elapsed_s, cached: e.cached };
    if (e.event === "stage_failed") next.stages[e.stage] = { ...prev, state: "failed", elapsed: e.elapsed_s, message: e.message };
  }
  if (e.event === "job_finished") { next.finished = true; next.decision = e.decision; }
  return next;
}

export function ProcessingView({ callId, inline = false, onFinished }: { callId: string; inline?: boolean; onFinished?: (d: Decision | null) => void }) {
  const [m, dispatch] = useReducer(reduce, undefined, init);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [attempt, setAttempt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [showLog, setShowLog] = useState(false);

  useEffect(() => {
    dispatch("reset");
    const sub = subscribeCallEvents(callId, dispatch, setStatus);
    return () => sub.close();
  }, [callId, attempt]);

  const running = Object.values(m.stages).some((s) => s.state === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [running]);

  useEffect(() => { if (m.finished) onFinished?.(m.decision); }, [m.finished, m.decision, onFinished]);

  const stageFailures = useMemo(() => Object.entries(m.stages).filter(([, s]) => s.state === "failed"), [m.stages]);
  const noHistory = status === "closed" && m.log.length === 0;

  // What each step produced, from the call's own documents (loaded once the job is finished; real numbers only).
  const docs = useAsync(async () => {
    if (!m.finished) return null;
    const [call, trace, transcript, analysis] = await Promise.all([
      getCall(callId).catch(() => null), getTrace(callId).catch(() => null), getTranscript(callId).catch(() => null), getAnalysis(callId).catch(() => null),
    ]);
    return { result: call?.kind === "result" ? call.data : null, trace, transcript, analysis };
  }, `proc-docs:${callId}:${m.finished}`);
  const produced = useMemo(() => producedBy(docs.data ?? null), [docs.data]);
  const shown = STAGES.filter((st) => st !== "upload" && st !== "analysis");

  return (
    <div className="stage-in space-y-5">
      {!inline && (
        <div className="space-y-1">
          <Link href={`/calls/${callId}`} className="text-sm text-muted-foreground hover:text-foreground">← Call {callId}</Link>
          <h1 className="text-headline font-semibold tracking-tight">How <span className="font-mono">{callId}</span> was processed</h1>
          <p className="text-body text-muted-foreground">
            {isLocalRun ? "Replay of the recorded run: each step with what it produced. Times appear only where the run recorded them; this is not live."
              : isFixtures ? "MOCK replay from fixtures." : "Live steps from the pipeline. A failed step never ends as “no alert”: the call goes to review."}
          </p>
        </div>
      )}

      {status === "reconnecting" && <div role="status" className="rounded-md border border-review bg-review-bg px-3 py-2 text-sm text-review">Reconnecting…</div>}
      {status === "failed" && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-alarm bg-alarm-bg px-3 py-2 text-sm text-alarm">
          <span>The live connection dropped after 3 attempts.</span>
          <Button variant="outline" size="sm" onClick={() => setAttempt((a) => a + 1)}><RefreshCw className="size-3.5" />Refresh</Button>
        </div>
      )}

      {noHistory ? (
        <EmptyState>No processing history for this call.</EmptyState>
      ) : (
        <section aria-label="Steps" className="elevated rounded-[var(--radius-panel)] p-6">
          <ol className="relative space-y-1" aria-live="polite">
            {shown.map((stage, i) => {
              const s = m.stages[stage];
              const notRun = m.finished && s.state === "waiting";
              const elapsed = s.state === "running" && s.startedAt ? (now - s.startedAt) / 1000 : s.elapsed;
              const what = s.state === "done" ? produced[stage] : null;
              return (
                <li key={stage} className={cn("relative grid grid-cols-[2rem_12rem_minmax(0,1fr)_5rem] items-start gap-3 rounded-xl px-3 py-2.5 transition-colors duration-[var(--dur-base)]",
                  s.state === "failed" && "bg-alarm-bg", s.state === "running" && "bg-muted")}>
                  {i < shown.length - 1 && <span aria-hidden className={cn("absolute left-[1.65rem] top-9 h-[calc(100%-1.25rem)] w-px", s.state === "done" ? "bg-foreground/40" : "bg-border")} />}
                  <StageIcon state={notRun ? "waiting" : s.state} notRun={notRun} />
                  <div>
                    <p className={cn("font-semibold", s.state === "waiting" && "text-muted-foreground")}>{STAGE_LABEL[stage] ?? stage}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">{stage}{s.cached ? " · from cache" : ""}</p>
                  </div>
                  <p className={cn("min-w-0 text-sm", s.state === "failed" ? "text-alarm" : "text-muted-foreground")}>
                    {s.state === "failed" ? <><AlertTriangle className="mr-1 inline size-3.5" />{s.message}</> : notRun ? "not run" : what ?? (s.state === "running" ? "working…" : "")}
                  </p>
                  <span className="tabular text-right text-sm">{elapsed != null && s.state !== "waiting" ? fmtSeconds(elapsed) : ""}</span>
                </li>
              );
            })}
          </ol>
          {m.finished && (
            <div className="mt-5 flex flex-wrap items-center gap-4 border-t border-border pt-5">
              <DecisionBadge decision={m.decision} size="lg" />
              {stageFailures.length > 0 && <p className="text-sm text-muted-foreground">A step failed, so the call went to <b>review</b>. It is never treated as “no alert”.</p>}
              <Link href={`/calls/${callId}`} className="ml-auto inline-flex h-11 items-center gap-2 rounded-full bg-primary px-6 font-semibold text-primary-foreground hover:opacity-90">Open the call <ArrowRight className="size-4" /></Link>
            </div>
          )}
        </section>
      )}

      {m.log.length > 0 && !isLocalRun && (
        <details className="rounded-2xl border border-border">
          <summary className="cursor-pointer px-5 py-3 text-sm font-semibold">Event log <span className="font-normal text-muted-foreground">({m.log.length} events)</span></summary>
          <pre className="max-h-72 overflow-auto border-t border-border p-4 font-mono text-xs leading-relaxed">
            {m.log.map((e) => `#${String(e.seq).padStart(2, "0")}  ${e.ts}  ${e.event}${e.stage ? ` ${e.stage}` : ""}${e.message ? `  — ${e.message}` : ""}`).join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}

const STAGE_LABEL: Partial<Record<Stage, string>> = {
  asr: "Speech to text", diarize: "Who is speaking", keywords: "Keywords", extract: "AI facts", validate: "Evidence check",
  rules: "Rules", confidence: "Confidence", decide: "Decision", narrate: "Explanation", snippets: "Audio passages", trigger: "Report",
};

type Docs = { result: CallResult | null; trace: DecisionTrace | null; transcript: Transcript | null; analysis: AnalysisArtifact | null } | null;
/** One line per step, counted from the call's documents. A step without a document says nothing rather than guessing. */
function producedBy(d: Docs): Partial<Record<Stage, string>> {
  if (!d) return {};
  const { result, trace, transcript } = d;
  const out: Partial<Record<Stage, string>> = {};
  if (transcript) {
    const n = transcript.segments.length;
    out.asr = transcript.mode === "reference" ? `reference transcript used, ${n} lines (no speech recognition in this run)` : `${n} segments${transcript.asr_model ? ` · ${transcript.asr_model}` : ""}`;
    const by = (sp: string) => transcript.segments.filter((x) => x.speaker === sp).length;
    out.diarize = by("unknown") === n ? "roles unknown: shown as Speaker" : `${by("advisor")} advisor · ${by("customer")} customer · ${by("unknown")} unknown lines`;
  }
  if (trace) {
    const fams = new Set(trace.keyword_hits.map((h) => h.family)).size;
    out.keywords = trace.keyword_hits.length ? `${trace.keyword_hits.length} hits in ${fams} famil${fams === 1 ? "y" : "ies"}` : "no keyword heard";
    out.extract = `${trace.facts.length} facts from the whole call`;
    const dropped = trace.facts.filter((f) => !f.valid).length;
    out.validate = `${trace.facts.length - dropped} verified${dropped ? `, ${dropped} dropped` : ""}`;
    const fired = trace.rules.filter((r) => r.fired);
    out.rules = fired.length ? fired.map((r) => `${CRITERION_LABEL[r.criterion] ?? r.criterion} fired (${Math.round(r.risk * 100)})`).join(", ") : `no rule fired (highest ${Math.round(Math.max(0, ...trace.rules.map((r) => r.risk)) * 100)})`;
    out.confidence = trace.confidence_breakdown ? `${Math.round(trace.confidence_breakdown.value * 100)} vs gate ${Math.round(trace.confidence_breakdown.gate * 100)}` : "not computed";
    out.decide = `${DECISION_LABEL[trace.decision]} (${trace.decision_path.replaceAll("_", " ")})`;
  }
  if (result) {
    out.narrate = result.narrative.startsWith(TEMPLATE_PREFIX) ? "template text (no LLM narrative in this run)" : "written after the decision was locked";
    const ev = result.findings.flatMap((f) => f.evidence);
    const cut = ev.filter((e) => e.snippet_path).length;
    out.snippets = cut ? `${cut} passages cut (±10 s)` : ev.some((e) => e.start_s == null) ? "none: no timestamps in this run" : "no passage to cut";
    out.trigger = result.decision === "alarm" ? "prepared for the trigger API (dry run unless configured)" : "nothing to report";
  }
  return out;
}

function StageIcon({ state, notRun }: { state: StageState["state"]; notRun: boolean }) {
  if (state === "running") return <Loader2 className="size-5 animate-spin text-info motion-reduce:animate-none" aria-label="running" />;
  if (state === "done") return <Check className="size-5 text-ok" aria-label="done" />;
  if (state === "failed") return <AlertTriangle className="size-5 text-alarm" aria-label="failed" />;
  return notRun ? <CircleDashed className="size-5 text-muted-foreground/60" aria-label="not run" /> : <Circle className="size-5 text-muted-foreground/60" aria-label="waiting" />;
}

export type { Stage };
