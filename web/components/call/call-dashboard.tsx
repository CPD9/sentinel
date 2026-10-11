"use client";
// Call page shell: status handling (loading, unknown call, still processing), then the call body below.
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { CallAudioProvider, useCallAudio } from "./audio-context";
import { CallHeader, CallSummary } from "./call-summary";
import { CallCopilot } from "@/components/copilot/call-copilot";
import { AuditTab } from "./tabs/audit-tab";
import { AudioTab } from "./tabs/audio-tab";
import { ReasoningTab } from "./tabs/reasoning-tab";
import { TranscriptTab } from "./tabs/transcript-tab";
import { AskCallPanel } from "@/components/copilot/ask-call-panel";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { ProcessingView } from "@/components/processing/processing-view";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, audioUrl, getAnalysis, getCall, getCalls, getTrace, getTranscript } from "@/lib/data";
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
  return <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" />Alerts</Link>;
}

function Loaded({ result, tab, sel }: { result: CallResult; tab: TabValue; sel: { win?: string; seg?: string } }) {
  return (
    <CallAudioProvider src={audioUrl(result.call_id)}>
      <Body result={result} tab={tab} sel={sel} />
    </CallAudioProvider>
  );
}

// Call page: the same top block as the inbox panel (decision, reason, risk, passage player, facts, actions), then the
// full transcript with the Standard German gloss, then the technical detail one click away under "Details".
function Body({ result, tab, sel }: { result: CallResult; tab: TabValue; sel: { win?: string; seg?: string } }) {
  const id = result.call_id;
  const router = useRouter();
  const audio = useCallAudio();
  const trace = useAsync(() => getTrace(id), `trace:${id}`);
  const transcript = useAsync(() => getTranscript(id), `tr:${id}`);
  const analysis = useAsync(() => getAnalysis(id), `an:${id}`);
  const calls = useAsync(getCalls, "calls");
  const item = calls.data?.find((c) => c.call_id === id);
  useReportMock(`result:${id}`, result);
  useReportMock(`trace:${id}`, trace.data);
  useReportMock(`analysis:${id}`, analysis.data);
  useReportMock(`transcript:${id}`, transcript.data);

  const brokenDoc = useCallback((s: { status: string; error: ApiError | null }) => s.status === "error" && s.error != null && s.error.status !== 404, []);
  const tabMarkers: Partial<Record<TabValue, boolean>> = { reasoning: brokenDoc(trace), audio: brokenDoc(analysis) };

  // A fact or cited line was clicked: highlight it in the transcript (URL ?seg=) and play from there when there is audio.
  const onCite = (segs: string[]) => {
    router.replace(`/calls/${id}?tab=${tab}&seg=${encodeURIComponent(segs.join(","))}`, { scroll: false });
    const start = transcript.data?.segments.find((s) => segs.includes(s.id))?.start_s;
    if (start != null && audio.available) audio.play(Math.max(0, start - 1), null);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <BackLink />
        <Link href={`/calls/${id}/processing`} className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">How this call was processed →</Link>
      </div>
      <article aria-label={`Call ${id}`} className="stage-in elevated rounded-[var(--radius-panel)]">
        <CallHeader meta={{ call_id: id, updated_at: item?.updated_at ?? null, duration_s: item?.duration_s ?? analysis.data?.duration_s ?? null, is_mock: item?.is_mock ?? false }} decision={result.decision} />
        <CallSummary meta={{ call_id: id, updated_at: item?.updated_at ?? null, duration_s: item?.duration_s ?? null, is_mock: item?.is_mock ?? false }}
          result={result} trace={trace} analysis={analysis} transcript={transcript} thresholds={trace.data?.thresholds ?? null} onCite={onCite} />
      </article>

      <AskCallPanel callId={id} onCite={onCite} />

      <section aria-labelledby="transcript-h" className="stage-in space-y-3" style={{ "--i": 1 } as React.CSSProperties}>
        <h2 id="transcript-h" className="text-title font-semibold tracking-tight">Transcript</h2>
        <TranscriptTab result={result} trace={trace} transcript={transcript} focusSeg={sel.seg} />
      </section>

      {/* copilot slot (web/copilot): renders nothing until that PR lands */}
      <CallCopilot callId={id} result={result} trace={trace.data ?? null} transcript={transcript.data ?? null} onCite={onCite} />

      <section aria-labelledby="details-h" className="space-y-3 pt-2">
        <div>
          <h2 id="details-h" className="text-title font-semibold tracking-tight">Details</h2>
          <p className="text-sm text-muted-foreground">For auditors: every step from facts to decision, the audio signals, and the versions used.</p>
        </div>
        <nav aria-label="Call details" className="overflow-x-auto border-b border-border">
          <ul className="flex min-w-max gap-6">
            {CALL_TABS.map((t) => (
              <li key={t.value}>
                <Link href={`/calls/${id}?tab=${t.value}${sel.seg ? `&seg=${encodeURIComponent(sel.seg)}` : ""}`} scroll={false} aria-current={tab === t.value ? "page" : undefined}
                  className={cn("-mb-px flex items-center gap-1.5 border-b-2 pb-2 text-lead", tab === t.value ? "border-foreground font-semibold" : "border-transparent text-muted-foreground hover:text-foreground")}>
                  {t.label}
                  {tabMarkers[t.value] && <span className="size-2 rounded-full bg-alarm" title="This tab's data failed to load" aria-label="error" />}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <section aria-label={tab} className="overflow-x-auto">
          {tab === "reasoning" && <ReasoningTab result={result} trace={trace} />}
          {tab === "audio" && <AudioTab result={result} analysis={analysis} selectedWindow={sel.win} />}
          {tab === "audit" && <AuditTab result={result} trace={trace} analysis={analysis} transcript={transcript} />}
        </section>
      </section>
    </div>
  );
}
