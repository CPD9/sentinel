"use client";
// Compact player for one evidence passage: the snippet is the passage with 10 s before and after, and the cited passage
// itself is highlighted on the progress line, so the officer sees "context, then the words". Replaces the browser's own
// audio bar (looks different in every browser). No audio (MOCK data, or a missing snippet) → a calm disabled state.
import { Pause, Play } from "lucide-react";
import { useRef, useState } from "react";
import { snippetUrl } from "@/lib/data";
import { fmtTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PassagePlayer({ callId, path, start, end, mock }: { callId: string; path: string | null; start: number; end: number; mock?: boolean }) {
  const url = snippetUrl(callId, path);
  const audio = useRef<HTMLAudioElement>(null);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState<number | null>(null);
  const off = Math.max(0, start - 10);              // where the snippet starts in the call
  const total = dur ?? end + 10 - off;               // estimate until the audio reports its length
  const unavailable = !url || failed;
  const at = (s: number) => `${Math.min(100, Math.max(0, (s / total) * 100))}%`;

  const toggle = () => {
    const a = audio.current;
    if (!a || unavailable) return;
    if (playing) a.pause(); else a.play().catch(() => setFailed(true));
  };

  return (
    <div className="flex items-center gap-3">
      <button type="button" onClick={toggle} disabled={unavailable}
        aria-label={unavailable ? "Audio not available" : playing ? "Pause the passage" : "Play the passage with 10 seconds before and after"}
        className={cn("grid size-9 shrink-0 place-items-center rounded-full transition-colors",
          unavailable ? "cursor-not-allowed bg-muted text-muted-foreground" : "bg-primary text-primary-foreground hover:opacity-90")}>
        {playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4 translate-x-px" aria-hidden />}
      </button>
      <div className="min-w-0 flex-1">
        <div className="relative h-1.5 rounded-full bg-muted" aria-hidden>
          <div className="absolute inset-y-0 rounded-full bg-primary/35" style={{ left: at(start - off), width: `calc(${at(end - off)} - ${at(start - off)})` }} />
          <div className="player-progress absolute inset-y-0 left-0 rounded-full bg-primary" style={{ width: at(t) }} />
        </div>
        <div className="tabular mt-1 flex justify-between gap-2 text-[11px] text-muted-foreground">
          <span>{fmtTime(off + t)}</span>
          <span className="truncate">{unavailable ? `Audio not available${mock ? " (MOCK data has no recordings)" : ""}` : "highlighted: the cited words"}</span>
          <span>{fmtTime(off + total)}</span>
        </div>
      </div>
      {url && (
        <audio ref={audio} src={url} preload="metadata" hidden
          onLoadedMetadata={(e) => isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration)}
          onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setT(0); }}
          onError={() => { setFailed(true); setPlaying(false); }} />
      )}
    </div>
  );
}
