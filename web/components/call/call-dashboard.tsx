"use client";
// Dashboard shell: shared header + URL-driven tabs. Structure after Leadership-Demo's project detail page
// (header, status handling, tab list with per-tab error marker, processing flow shown inline while running).
import { AlertTriangle, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import { CallAudioProvider } from "./audio-context";
import { FeedbackBar } from "./feedback-bar";
import { AuditTab } from "./tabs/audit-tab";
import { AudioTab } from "./tabs/audio-tab";
import { EvidenceTab } from "./tabs/evidence-tab";
import { ReasoningTab } from "./tabs/reasoning-tab";
import { SummaryTab } from "./tabs/summary-tab";
import { TranscriptTab } from "./tabs/transcript-tab";
import { DecisionBadge, StageErrorChip } from "@/components/shell/badges";
import { RiskConfidence } from "@/components/shell/score";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { ProcessingView } from "@/components/processing/processing-view";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, audioUrl, getAnalysis, getCall, getTrace, getTranscript } from "@/lib/data";
import { useReportMock } from "@/lib/mock-store";
import { CALL_TABS, type TabValue } from "@/lib/tabs";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";
import type { CallResult } from "@/lib/types";

export function CallDashboard({ id, tab, sel }: { id: string; tab: TabValue; sel: { win?: string; seg?: string } }) {
  const call = useAsync(() => getCall(id), `call:${id}`);

  if (call.status === "loading" && !call.data) {
    return (
      <div aria-busy="true" className="space-y-4">
        <Skeleton className="h-8 w-64" /><Skeleton className="h-6 w-96" /><SkeletonBlock rows={6} />
      </div>
    );
  }
  if (call.status === "error" && !call.data) {
    return call.error.status === 404 && call.error.code !== "not_available" ? (
      <div className="space-y-3"><BackLink /><ErrorCard error={call.error} title="Unknown call" /></div>
    ) : (
      <div className="space-y-3"><BackLink /><ErrorCard error={call.error} onRetry={call.reload} /></div>
    );
  }
  const detail = call.data!;
  if (detail.kind === "pending") {
    return (
      <div className="space-y-4">
        <BackLink />
        <h1 className="text-xl font-semibold tracking-tight"><span className="font-mono">{id}</span> <span className="text-sm font-normal text-muted-foreground">still processing</span></h1>
        <ProcessingView callId={id} inline onFinished={() => setTimeout(call.reload, 600)} />
      </div>
    );
  }
  return <Loaded result={detail.data} tab={tab} sel={sel} />;
}

function BackLink() {
  return <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" />Overview</Link>;
}

function Loaded({ result, tab, sel }: { result: CallResult; tab: TabValue; sel: { win?: string; seg?: string } }) {
  const id = result.call_id;
  const trace = useAsync(() => getTrace(id), `trace:${id}`);
  const transcript = useAsync(() => getTranscript(id), `tr:${id}`);
  const analysis = useAsync(() => getAnalysis(id), `an:${id}`);
  useReportMock(`result:${id}`, result);
  useReportMock(`trace:${id}`, trace.data);
  useReportMock(`analysis:${id}`, analysis.data);
  useReportMock(`transcript:${id}`, transcript.data);

  const brokenDoc = useCallback((s: { status: string; error: ApiError | null }) => s.status === "error" && s.error != null && s.error.status !== 404, []);
  const tabMarkers: Partial<Record<TabValue, boolean>> = {
    reasoning: brokenDoc(trace), audio: brokenDoc(analysis), transcript: brokenDoc(transcript) || (transcript.status === "error" && result.stage_errors.length > 0),
  };
  const gate = trace.data?.thresholds.confidence_gate;

  return (
    <CallAudioProvider src={audioUrl(id)}>
      <div className="space-y-5">
        <BackLink />
        <header className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h1 className="font-mono text-xl font-semibold tracking-tight">{id}</h1>
            <DecisionBadge decision={result.decision} size="lg" />
            <StageErrorChip count={result.stage_errors.length} />
            <RiskConfidence risk={result.risk_score} confidence={result.confidence} gate={gate} />
          </div>
          <FeedbackBar callId={id} decision={result.decision} />
          {result.stage_errors.length > 0 && (
            <div role="alert" className="rounded-md border border-alarm bg-alarm-bg px-3 py-2 text-sm text-alarm">
              <p className="flex items-center gap-2 font-semibold"><AlertTriangle className="size-4" />Stage error — this call was not fully analysed, so it is routed to review.</p>
              <ul className="mt-1 list-disc pl-6">
                {result.stage_errors.map((e, i) => <li key={i}><code className="font-mono">{e.stage}</code>: {e.message}</li>)}
              </ul>
            </div>
          )}
        </header>

        <div className="grid gap-6 lg:grid-cols-2">
          <section aria-labelledby="verdict" className="min-w-0 space-y-3">
            <h2 id="verdict" className="text-lg font-semibold tracking-tight">Verdict &amp; reasoning</h2>
            <SummaryTab result={result} trace={trace} stacked />
          </section>
          <section id="passages" aria-labelledby="passages-h" className="min-w-0 scroll-mt-20 space-y-3">
            <h2 id="passages-h" className="text-lg font-semibold tracking-tight">Passages that carry the decision</h2>
            <EvidenceTab result={result} analysis={analysis} stacked />
          </section>
        </div>

        <div className="space-y-1 pt-2">
          <h2 className="text-lg font-semibold tracking-tight">Details for auditors</h2>
          <p className="text-sm text-muted-foreground">The full transcript, the step-by-step decision, the audio signals and the versions used.</p>
        </div>
        <nav aria-label="Call details" className="-mx-4 overflow-x-auto border-b border-border px-4">
          <ul className="flex min-w-max gap-1">
            {CALL_TABS.map((t) => (
              <li key={t.value}>
                <Link href={`/calls/${id}?tab=${t.value}`} scroll={false} aria-current={tab === t.value ? "page" : undefined}
                  className={cn("relative flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm", tab === t.value ? "border-primary font-semibold text-link" : "border-transparent text-muted-foreground hover:text-foreground")}>
                  {t.label}
                  {tabMarkers[t.value] && <span className="size-2 rounded-full bg-alarm" title="This tab's data failed to load" aria-label="error" />}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <section aria-label={tab}>
          {tab === "transcript" && <TranscriptTab result={result} trace={trace} transcript={transcript} focusSeg={sel.seg} />}
          {tab === "audio" && <AudioTab result={result} analysis={analysis} selectedWindow={sel.win} />}
          {tab === "reasoning" && <ReasoningTab result={result} trace={trace} />}
          {tab === "audit" && <AuditTab result={result} trace={trace} analysis={analysis} transcript={transcript} />}
        </section>
      </div>
    </CallAudioProvider>
  );
}
