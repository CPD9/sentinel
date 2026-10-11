"use client";
// "What was said" for the Overview panel: a short transcript excerpt around the cited passages, and ONE player under it.
//   - cited lines are bold and clickable (the click chooses which passage the player plays), one line before and after
//     each cited line is shown in grey for context, keywords found by the keyword step are underlined
//   - the player plays the passage's snippet (10 s before and after, as the case asks) over the call's real waveform,
//     with the cited words highlighted on it
// Without a transcript (e.g. ASR failed) the excerpt falls back to the cited quotes only; without a waveform the player
// shows a plain bar; without audio (MOCK data) the play button is disabled, like PassagePlayer.
import { Pause, Play } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { SPEAKER_COLOR } from "@/lib/colors";
import { snippetUrl } from "@/lib/data";
import { fmtTime } from "@/lib/format";
import type { Evidence, KeywordHit, Speaker, Transcript, WaveformPeaks } from "@/lib/types";
import { cn } from "@/lib/utils";

const BARS = 72;                          // waveform bars across the player, whatever the snippet length
const speakerName = (s: Speaker) => (s === "advisor" ? "Advisor" : s === "customer" ? "Customer" : "Unknown");

type Line = { key: string; speaker: Speaker; start: number | null; text: string; segment: string | null; passage: number | null } | { key: string; gap: true };

/** Excerpt lines: each cited segment with one neighbour on each side, in time order, "…" where lines were skipped. */
function buildLines(passages: Evidence[], transcript: Transcript | null): Line[] {
  const segs = transcript?.segments ?? [];
  const citedAt = new Map<number, number>();                       // segment index → passage index
  passages.forEach((p, pi) => p.segment_ids.forEach((sid) => {
    const i = segs.findIndex((s) => s.id === sid);
    if (i >= 0 && !citedAt.has(i)) citedAt.set(i, pi);
  }));
  if (citedAt.size === 0) {                                          // no transcript: the quotes themselves
    return passages.map((p, pi) => ({ key: `p${pi}`, speaker: p.speaker, start: p.start_s, text: p.text, segment: p.segment_ids[0] ?? null, passage: pi }));
  }
  const keep = new Set<number>();
  for (const i of citedAt.keys()) for (const j of [i - 1, i, i + 1]) if (j >= 0 && j < segs.length) keep.add(j);
  const out: Line[] = [];
  let prev = -1;
  for (const i of [...keep].sort((a, b) => a - b)) {
    if (prev >= 0 && i > prev + 1) out.push({ key: `gap${i}`, gap: true });
    const s = segs[i];
    out.push({ key: s.id, speaker: s.speaker, start: s.start_s, text: s.text, segment: s.id, passage: citedAt.get(i) ?? null });
    prev = i;
  }
  return out;
}

/** The text with every keyword match underlined. */
function Underlined({ text, words }: { text: string; words: string[] }) {
  const uniq = [...new Set(words.filter(Boolean))];
  if (uniq.length === 0) return <>{text}</>;
  const re = new RegExp(`(${uniq.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return <>{text.split(re).map((part, i) => (i % 2 === 1
    ? <span key={i} className="underline decoration-2 underline-offset-4">{part}</span>
    : <span key={i}>{part}</span>))}</>;
}

export function ExcerptPlayer({ callId, passages, transcript, hits, waveform, mock }: {
  callId: string; passages: Evidence[]; transcript: Transcript | null; hits: KeywordHit[]; waveform: WaveformPeaks | null; mock: boolean;
}) {
  const lines = useMemo(() => buildLines(passages, transcript), [passages, transcript]);
  const [sel, setSel] = useState(0);
  const p = passages[Math.min(sel, passages.length - 1)];

  return (
    <div className="space-y-4">
      <ol className="max-h-56 space-y-1 overflow-y-auto pr-1 text-[15px] leading-relaxed" aria-label="What was said">
        {lines.map((l) => {
          if ("gap" in l) return <li key={l.key} aria-hidden className="pl-2 text-muted-foreground sm:pl-[8.5rem]">…</li>;
          const cited = l.passage != null;
          const active = cited && l.passage === sel;
          const row = (
            <>
              <span className="w-20 shrink-0 font-medium" style={cited ? { color: SPEAKER_COLOR[l.speaker] } : undefined}>{speakerName(l.speaker)}</span>
              <span className="tabular w-12 shrink-0 text-muted-foreground">{fmtTime(l.start)}</span>
              <span lang="gsw" className="min-w-0 basis-full sm:basis-0 sm:flex-1">“<Underlined text={l.text} words={hits.filter((h) => h.segment_id === l.segment).map((h) => h.matched_text)} />”</span>
            </>
          );
          return (
            <li key={l.key}>
              {cited ? (
                <button type="button" onClick={() => setSel(l.passage!)} aria-pressed={active}
                  title="Play this passage" className={cn("flex w-full flex-wrap gap-x-2 rounded-md px-2 py-0.5 text-left font-semibold transition-colors sm:flex-nowrap",
                    active ? "bg-primary/12" : "hover:bg-muted")}>{row}</button>
              ) : (
                <div className="flex flex-wrap gap-x-2 px-2 py-0.5 text-muted-foreground sm:flex-nowrap">{row}</div>
              )}
            </li>
          );
        })}
      </ol>
      {p && p.start_s != null && p.end_s != null && (
        <WavePlayer key={`${sel}`} url={snippetUrl(callId, p.snippet_path)} start={p.start_s} end={p.end_s} waveform={waveform} mock={mock} />
      )}
    </div>
  );
}

function WavePlayer({ url, start, end, waveform, mock }: { url: string | null; start: number; end: number; waveform: WaveformPeaks | null; mock: boolean }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const off = Math.max(0, start - 10);                       // where the snippet starts in the call
  const total = end + 10 - off;
  const unavailable = !url || failed;
  const noAudio = `No audio for this passage${mock ? " (MOCK data has no recordings)" : ""}`;

  // Bar heights for the snippet window, from the call's waveform peaks (normalised to the loudest bar of the window).
  const bars = useMemo(() => {
    if (!waveform || waveform.max.length === 0) return null;
    const out: number[] = [];
    for (let b = 0; b < BARS; b++) {
      const from = Math.floor((off + (b / BARS) * total) / waveform.bucket_s);
      const to = Math.max(from + 1, Math.floor((off + ((b + 1) / BARS) * total) / waveform.bucket_s));
      let peak = 0;
      for (let i = from; i < to && i < waveform.max.length; i++) peak = Math.max(peak, Math.abs(waveform.max[i]), Math.abs(waveform.min[i] ?? 0));
      out.push(peak);
    }
    const top = Math.max(...out, 1e-6);
    return out.map((v) => v / top);
  }, [waveform, off, total]);

  const toggle = () => {
    const a = audio.current;
    if (!a || unavailable) return;
    if (playing) a.pause(); else a.play().catch(() => setFailed(true));
  };
  const at = (s: number) => (s - off) / total;               // 0–1 position in the snippet

  return (
    <div className="flex items-center gap-4">
      <button type="button" onClick={toggle} disabled={unavailable} title={unavailable ? noAudio : undefined}
        aria-label={unavailable ? noAudio : playing ? "Pause the passage" : "Play the passage with 10 seconds before and after"}
        className={cn("grid size-12 shrink-0 place-items-center rounded-full transition-[transform,opacity] active:scale-95 motion-reduce:transition-none",
          unavailable ? "cursor-not-allowed bg-muted text-muted-foreground" : "bg-foreground text-background hover:opacity-90")}>
        {playing ? <Pause className="size-5" aria-hidden /> : <Play className="size-5 translate-x-px" aria-hidden />}
      </button>
      <div className="min-w-0 flex-1">
        {bars ? (
          <div className="flex h-12 items-center gap-[2px]" aria-hidden>
            {bars.map((v, i) => {
              const pos = (i + 0.5) / BARS;
              const cited = pos >= at(start) && pos <= at(end);
              const played = !unavailable && pos <= t / total;
              return <span key={i} className={cn("flex-1 rounded-full", played ? "bg-foreground" : cited ? "bg-primary" : "bg-muted-foreground/35")}
                style={{ height: `${Math.max(8, v * 100)}%` }} />;
            })}
          </div>
        ) : (
          <div className="relative h-1.5 rounded-full bg-muted" aria-hidden>
            <div className="absolute inset-y-0 rounded-full bg-primary/50" style={{ left: `${at(start) * 100}%`, width: `${(at(end) - at(start)) * 100}%` }} />
            <div className="player-progress absolute inset-y-0 left-0 rounded-full bg-foreground" style={{ width: `${(t / total) * 100}%` }} />
          </div>
        )}
        <div className="tabular mt-1 flex justify-between gap-2 text-[11px] text-muted-foreground">
          <span>{fmtTime(off + t)}</span>
          <span className="truncate">{unavailable && `${noAudio} · `}<span className="text-link">■</span> the cited words</span>
          <span>{fmtTime(off + total)}</span>
        </div>
      </div>
      {url && (
        <audio ref={audio} src={url} preload="metadata" hidden
          onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setT(0); }}
          onError={() => { setFailed(true); setPlaying(false); }} />
      )}
    </div>
  );
}
