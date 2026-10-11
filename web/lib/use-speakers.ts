"use client";
// Display-only speaker roles (advisor / customer) from scripts/assign_speakers.py, laid over an ASR transcript whose
// segments are all "unknown". Never feeds the decision; absent roles leave the transcript untouched.
import { useMemo } from "react";
import { getSpeakers } from "./data";
import type { SpeakerRoles, Transcript } from "./types";
import { useAsync, type Loadable } from "./use-async";

export function useSpeakerRoles(id: string): SpeakerRoles | null {
  return useAsync(() => getSpeakers(id), `spk:${id}`).data ?? null;
}

export const speakerSource = (r: SpeakerRoles) => r.label_source === "acoustic + content"
  ? `acoustic + content (${r.diarizer ?? "diarizer"} voices, roles assigned by ${r.mapper.model ?? "the LLM"})`
  : `content only (${r.mapper.model ?? "the LLM"} from the text, no acoustic separation)`;

function overlay(t: Transcript | null, r: SpeakerRoles | null): Transcript | null {
  if (!t || !r) return t;
  const by = new Map(r.segments.map((s) => [s.id, s]));
  if (by.size !== t.segments.length || t.segments.some((s) => !by.has(s.id))) return t;     // stale join: show nothing
  return {
    ...t, speaker_source: speakerSource(r),
    segments: t.segments.map((s) => {
      const x = by.get(s.id)!;
      return s.speaker === "unknown" ? { ...s, speaker: x.role, role_mixed: !!x.mixed } : s;
    }),
  };
}

export function useSpeakerOverlay(id: string, transcript: Loadable<Transcript>): Loadable<Transcript> {
  const roles = useSpeakerRoles(id);
  const data = useMemo(() => overlay(transcript.data, roles), [transcript.data, roles]);
  return data === transcript.data ? transcript : ({ ...transcript, data } as Loadable<Transcript>);
}
