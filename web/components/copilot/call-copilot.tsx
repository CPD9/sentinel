"use client";
// SLOT for the copilot (merged in #38): renders "Ask about this call" (ask-call-panel.tsx) under the call summary.
// Contract for the copilot:
//   - mounted once per call page, inside the call's audio provider (useCallAudio() works: seek/play a cited passage)
//   - props below are already loaded by the page; fetch anything else through lib/data.ts only
//   - placement: a right-side drawer or a section below "Details". Keep clear of the demo bar (fixed, bottom centre,
//     z-50) and the sticky nav (top, z-30): use z-40 and the right edge. Respect prefers-reduced-motion.
//   - read-only by default: it may explain and cite, it must not change a decision or post feedback by itself
import { AskCallPanel } from "@/components/copilot/ask-call-panel";
import type { CallResult, DecisionTrace, JudgeVerdict, Transcript } from "@/lib/types";

export interface CallCopilotProps {
  callId: string;
  result: CallResult;
  trace: DecisionTrace | null;
  transcript: Transcript | null;
  judge?: JudgeVerdict | null;
  /** highlight a passage in the transcript and seek the audio (the same path as clicking a fact) */
  onCite: (segmentIds: string[]) => void;
}

export function CallCopilot({ callId, onCite }: CallCopilotProps) {
  return <AskCallPanel callId={callId} onCite={onCite} />;
}
