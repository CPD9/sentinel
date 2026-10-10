"use client";
import { ArrowUpRight, FileText } from "lucide-react";
import Link from "next/link";
import { CounterChip, CriterionChip, SpeakerChip } from "@/components/shell/badges";
import { EmptyState } from "@/components/shell/states";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SnippetPlayer } from "../snippet-player";
import { criterionColor } from "@/lib/colors";
import { fmtRange, pct } from "@/lib/format";
import type { AnalysisArtifact, CallResult, Evidence } from "@/lib/types";
import type { Loadable } from "@/lib/use-async";

export function EvidenceTab({ result, analysis }: { result: CallResult; analysis: Loadable<AnalysisArtifact> }) {
  const withEvidence = result.findings.map((f, fi) => ({ f, fi })).filter(({ f }) => f.evidence.length > 0 || f.counter_evidence.length > 0);
  if (withEvidence.length === 0) return <EmptyState>This call has no evidence passages.</EmptyState>;
  const wave = analysis.data?.waveform_peaks ?? null;
  const windowOf = (fi: number, ei: number) => analysis.data?.evidence_windows.find((w) => w.finding_index === fi && w.evidence_index === ei);

  return (
    <div className="space-y-6">
      {withEvidence.map(({ f, fi }) => (
        <section key={fi} aria-label={f.criterion} className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 border-l-4 pl-3" style={{ borderColor: criterionColor(f.criterion) }}>
            <CriterionChip criterion={f.criterion} /><span className="tabular text-sm font-semibold">risk {pct(f.risk)}</span>
            <span className="text-sm text-muted-foreground">{f.reason}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {f.evidence.map((e, ei) => (
              <EvidenceCard key={`e${ei}`} callId={result.call_id} e={e} wave={wave}
                inAudio={windowOf(fi, ei) ? `/calls/${result.call_id}?tab=audio&win=${fi}.${ei}` : null} />
            ))}
            {f.counter_evidence.map((e, ci) => <EvidenceCard key={`c${ci}`} callId={result.call_id} e={e} wave={wave} counter inAudio={null} />)}
          </div>
        </section>
      ))}
    </div>
  );
}

function EvidenceCard({ callId, e, wave, counter, inAudio }: {
  callId: string; e: Evidence; wave: AnalysisArtifact["waveform_peaks"] | null; counter?: boolean; inAudio: string | null;
}) {
  const hasTime = e.start_s != null && e.end_s != null;
  return (
    <Card className={counter ? "bg-muted/60" : ""}>
      <CardHeader className="pb-0">
        <div className="flex flex-wrap items-center gap-2">
          {counter && <CounterChip />}
          <SpeakerChip speaker={e.speaker} />
          <span className="tabular text-xs text-muted-foreground">{hasTime ? fmtRange(e.start_s, e.end_s) : "no timestamp (reference transcript)"}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <blockquote lang="gsw" className={`border-l-2 pl-3 text-sm leading-relaxed ${counter ? "border-muted-foreground/50 text-muted-foreground" : "border-foreground/60"}`}>“{e.text}”</blockquote>
        {!counter && hasTime && <SnippetPlayer callId={callId} path={e.snippet_path} start={e.start_s!} end={e.end_s!} waveform={wave} />}
        <div className="flex flex-wrap gap-3 text-xs">
          <Link href={`/calls/${callId}?tab=transcript&seg=${e.segment_ids.join(",")}`} className="inline-flex items-center gap-1 underline underline-offset-2"><FileText className="size-3" />Jump to transcript</Link>
          {inAudio && <Link href={inAudio} className="inline-flex items-center gap-1 underline underline-offset-2"><ArrowUpRight className="size-3" />Show in audio analysis</Link>}
        </div>
      </CardContent>
    </Card>
  );
}
