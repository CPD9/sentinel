"use client";
import { DocGate } from "@/components/shell/states";
import { AudioLanes } from "@/components/audio/lanes";
import { LanguageRouting } from "@/components/audio/swiss-map";
import type { AnalysisArtifact, CallResult } from "@/lib/types";
import type { Loadable } from "@/lib/use-async";

export function AudioTab({ result, analysis, selectedWindow }: { result: CallResult; analysis: Loadable<AnalysisArtifact>; selectedWindow?: string }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        All lanes share one time axis. <b className="text-foreground">Only the audio-quality lane feeds the decision</b> (via the confidence gate); every other lane explains what the system heard and never changes the outcome.
      </p>
      <DocGate state={analysis} unavailable="Audio analysis not computed for this call." rows={8}>
        {(a) => <AudioLanes a={a} result={result} initialWindow={selectedWindow} />}
      </DocGate>
      <LanguageRouting callId={result.call_id} />
    </div>
  );
}
