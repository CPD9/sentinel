"use client";
// Stage timeline, driven by ProcessingEvents. Step-by-step status idea adapted from Leadership-Demo's processing-flow / phase-card,
// but driven by real events instead of a time estimate.
import { AlertTriangle, ArrowRight, Check, Circle, CircleDashed, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useReducer, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DecisionBadge } from "@/components/shell/badges";
import { EmptyState } from "@/components/shell/states";
import { subscribeCallEvents, type StreamStatus } from "@/lib/data";
import { fmtSeconds } from "@/lib/format";
import type { Decision, ProcessingEvent, Stage } from "@/lib/types";
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

  return (
    <div className="space-y-4">
      {!inline && (
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Processing <span className="font-mono">{callId}</span></h1>
          <p className="text-sm text-muted-foreground">Live stages from the pipeline. A failed stage does not stop the timeline: the call ends as review.</p>
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
        <Card>
          <CardHeader><CardTitle>Stages</CardTitle>
            {m.finished && (
              <div className="flex items-center gap-3">
                <DecisionBadge decision={m.decision} />
                <Link href={`/calls/${callId}`} className="inline-flex h-8 items-center gap-1 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground">Open call <ArrowRight className="size-3.5" /></Link>
              </div>
            )}
          </CardHeader>
          <CardContent>
            <ol className="space-y-1" aria-live="polite">
              {STAGES.map((stage) => {
                const s = m.stages[stage];
                const notRun = m.finished && s.state === "waiting";
                const elapsed = s.state === "running" && s.startedAt ? (now - s.startedAt) / 1000 : s.elapsed;
                return (
                  <li key={stage} className={cn("rounded-md border px-3 py-2", s.state === "failed" ? "border-alarm bg-alarm-bg" : "border-transparent", s.state === "running" && "border-info bg-info-bg")}>
                    <div className="flex items-center gap-3">
                      <StageIcon state={notRun ? "waiting" : s.state} notRun={notRun} />
                      <span className={cn("w-28 font-mono text-sm", (s.state === "waiting") && "text-muted-foreground")}>{stage}</span>
                      <span className="text-xs text-muted-foreground">{notRun ? "not run" : s.state}</span>
                      {s.cached && <span className="rounded border border-border px-1.5 text-[11px]" title="Result reused from cache">from cache</span>}
                      <span className="tabular ml-auto text-sm">{elapsed != null && s.state !== "waiting" ? fmtSeconds(elapsed) : ""}</span>
                    </div>
                    {s.state === "failed" && s.message && <p className="mt-1 pl-8 text-sm text-alarm"><AlertTriangle className="mr-1 inline size-3.5" />{s.message}</p>}
                  </li>
                );
              })}
            </ol>
            {stageFailures.length > 0 && m.finished && <p className="mt-3 text-sm text-muted-foreground">The call ended as <b>review</b> because a stage failed. It is never treated as “no alert”.</p>}
          </CardContent>
        </Card>
      )}

      {m.log.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Event log</CardTitle>
            <Button variant="ghost" size="sm" onClick={() => setShowLog((v) => !v)} aria-expanded={showLog}>{showLog ? "Hide" : `Show (${m.log.length})`}</Button>
          </CardHeader>
          {showLog && (
            <CardContent>
              <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
                {m.log.map((e) => `#${String(e.seq).padStart(2, "0")}  ${e.ts}  ${e.event}${e.stage ? ` ${e.stage}` : ""}${e.message ? `  — ${e.message}` : ""}`).join("\n")}
              </pre>
            </CardContent>
          )}
        </Card>
      )}
    </div>
  );
}

function StageIcon({ state, notRun }: { state: StageState["state"]; notRun: boolean }) {
  if (state === "running") return <Loader2 className="size-5 animate-spin text-info motion-reduce:animate-none" aria-label="running" />;
  if (state === "done") return <Check className="size-5 text-ok" aria-label="done" />;
  if (state === "failed") return <AlertTriangle className="size-5 text-alarm" aria-label="failed" />;
  return notRun ? <CircleDashed className="size-5 text-muted-foreground/60" aria-label="not run" /> : <Circle className="size-5 text-muted-foreground/60" aria-label="waiting" />;
}

export type { Stage };
