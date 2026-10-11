"use client";
// "What was said" for the Overview panel: a short transcript excerpt around the cited passages, and ONE player under it.
//   - cited lines are bold and clickable (the click chooses which passage the player plays), one line before and after
//     each cited line is shown in grey for context, keywords found by the keyword step are underlined
//   - the player plays the passage's snippet (10 s before and after, as the case asks) over the call's real waveform,
//     with the cited words highlighted on it
// Without a transcript (e.g. ASR failed) the excerpt falls back to the cited quotes only; without a waveform the player
// shows a plain bar; without audio (MOCK data) the play button is disabled. Reference transcripts have no timestamps:
// then there is no player, and the excerpt says so instead of pretending.
// Cited lines show the Standard German gloss (Fact.gloss_de) side by side; facts clicked elsewhere focus their line.
import { Pause, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { SPEAKER_COLOR } from "@/lib/colors";
import { snippetUrl } from "@/lib/data";
import { speakerLabel } from "@/lib/explain";
import { fmtTime } from "@/lib/format";
import type { Evidence, KeywordHit, Speaker, Transcript, WaveformPeaks } from "@/lib/types";
import { cn } from "@/lib/utils";

const BARS = 72;                          // waveform bars across the player, whatever the snippet length

type Line = { key: string; speaker: Speaker; judge?: Speaker; start: number | null; text: string; segment: string | null; passage: number | null; cited: boolean } | { key: string; gap: true };

/** Excerpt lines: each cited segment (passages + the facts shown next to it) with one neighbour on each side, in time
 *  order, "…" where lines were skipped. */
function buildLines(passages: Evidence[], transcript: Transcript | null, extra: string[]): Line[] {
  const segs = transcript?.segments ?? [];
  const citedAt = new Map<number, number>();                       // segment index → passage index
  passages.forEach((p, pi) => p.segment_ids.forEach((sid) => {
    const i = segs.findIndex((s) => s.id === sid);
    if (i >= 0 && !citedAt.has(i)) citedAt.set(i, pi);
  }));
  const factAt = new Set(extra.map((sid) => segs.findIndex((s) => s.id === sid)).filter((i) => i >= 0));
  if (citedAt.size === 0 && factAt.size === 0) {                    // no transcript: the quotes themselves
    return passages.map((p, pi) => ({ key: `p${pi}`, speaker: p.speaker, start: p.start_s, text: p.text, segment: p.segment_ids[0] ?? null, passage: pi, cited: true }));
  }
  const keep = new Set<number>();
  for (const i of [...citedAt.keys(), ...factAt]) for (const j of [i - 1, i, i + 1]) if (j >= 0 && j < segs.length) keep.add(j);
  const out: Line[] = [];
  let prev = -1;
  for (const i of [...keep].sort((a, b) => a - b)) {
    if (prev >= 0 && i > prev + 1) out.push({ key: `gap${i}`, gap: true });
    const s = segs[i];
    // the transcript's (diarized) role; the judge's own role for the citation when the transcript has none, or as a
    // note when the two disagree
    const pi = citedAt.get(i), judge = pi != null ? passages[pi].speaker : undefined;
    out.push({ key: s.id, speaker: s.speaker === "unknown" && judge ? judge : s.speaker,
      judge: judge && judge !== "unknown" && s.speaker !== "unknown" && judge !== s.speaker ? judge : undefined, start: s.start_s, text: s.text, segment: s.id, passage: citedAt.get(i) ?? null, cited: citedAt.has(i) || factAt.has(i) });
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

export function ExcerptPlayer({ callId, passages, transcript, hits, waveform, mock, gloss, factSegments = [], focus }: {
  callId: string; passages: Evidence[]; transcript: Transcript | null; hits: KeywordHit[]; waveform: WaveformPeaks | null; mock: boolean;
  /** segment id → Standard German gloss of the fact quoted there */
  gloss?: Map<string, string>;
  /** segments cited by the facts shown next to the excerpt, so a click on a fact always has a line to land on */
  factSegments?: string[];
  /** set by a click on a fact: highlight that line and, if it belongs to a passage, select it for the player */
  focus?: { segs: string[]; n: number } | null;
}) {
  const lines = useMemo(() => buildLines(passages, transcript, factSegments), [passages, transcript, factSegments]);
  // The player's passage: the last line clicked here, unless a fact was clicked since then (focus.n is newer).
  const [pick, setPick] = useState<{ i: number; n: number }>({ i: 0, n: -1 });
  const focusPassage = useMemo(() => {
    if (!focus) return null;
    const hit = lines.find((l) => !("gap" in l) && l.segment && focus.segs.includes(l.segment));
    return hit && !("gap" in hit) ? hit.passage : null;
  }, [focus, lines]);
  const sel = focus && focus.n > pick.n && focusPassage != null ? focusPassage : pick.i;
  const setSel = (i: number) => setPick({ i, n: focus?.n ?? -1 });
  const listRef = useRef<HTMLOListElement>(null);
  const p = passages[Math.min(sel, passages.length - 1)];
  const hasGloss = !!gloss && lines.some((l) => !("gap" in l) && l.segment && gloss.has(l.segment));
  const focused = new Set(focus?.segs ?? []);

  // A fact was clicked: bring its line into view.
  useEffect(() => {
    if (!focus) return;
    listRef.current?.querySelector<HTMLElement>(`[data-seg="${focus.segs[0]}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.n]);

  const cols = hasGloss ? "sm:grid-cols-[5.5rem_3rem_minmax(0,1fr)_minmax(0,1fr)]" : "sm:grid-cols-[5.5rem_3rem_minmax(0,1fr)]";
  const noTimes = p != null && (p.start_s == null || p.end_s == null);

  return (
    <div className="space-y-4">
      {hasGloss && (
        <div className={cn("hidden gap-x-3 px-2 sm:grid", cols)} aria-hidden>
          <span /><span /><span className="eyebrow">Swiss German (said)</span><span className="eyebrow">Standard German (gloss)</span>
        </div>
      )}
      <ol ref={listRef} className="max-h-64 space-y-0.5 overflow-y-auto pr-1 text-body" aria-label="What was said">
        {lines.map((l) => {
          if ("gap" in l) return <li key={l.key} aria-hidden className="pl-2 text-muted-foreground sm:pl-[9.5rem]">…</li>;
          const active = l.passage != null && l.passage === sel;
          const g = l.segment ? gloss?.get(l.segment) : undefined;
          const isFocus = l.segment != null && focused.has(l.segment);
          const row = (
            <>
              <span className="font-medium" style={l.cited ? { color: SPEAKER_COLOR[l.speaker] } : undefined}>{speakerLabel(l.speaker)}
                {l.judge && <span className="block text-[10px] font-normal text-muted-foreground" title="The judge attributed this citation to a different role">judge: {speakerLabel(l.judge)}</span>}</span>
              <span className="tabular text-muted-foreground">{fmtTime(l.start)}</span>
              <span lang="gsw" className="min-w-0">“<Underlined text={l.text} words={hits.filter((h) => h.segment_id === l.segment).map((h) => h.matched_text)} />”</span>
              {hasGloss && <span lang="de" className="min-w-0 font-normal text-muted-foreground">{g ? `“${g}”` : ""}</span>}
            </>
          );
          const cls = cn("grid w-full grid-cols-[5.5rem_3rem_minmax(0,1fr)] gap-x-3 rounded-md px-2 py-1 text-left", cols,
            isFocus && `jumped ring-1 ring-foreground/50`);
          return (
            <li key={`${l.key}-${isFocus ? focus?.n : 0}`} data-seg={l.segment ?? undefined}>
              {l.passage != null ? (
                <button type="button" onClick={() => setSel(l.passage!)} aria-pressed={active} title="Play this passage"
                  className={cn(cls, "font-semibold transition-colors", active ? "bg-primary/12" : "hover:bg-muted")}>{row}</button>
              ) : (
                <div className={cn(cls, l.cited ? "font-semibold" : "text-muted-foreground")}>{row}</div>
              )}
            </li>
          );
        })}
      </ol>
      {p && !noTimes && (
        <WavePlayer key={`${sel}`} url={snippetUrl(callId, p.snippet_path)} start={p.start_s!} end={p.end_s!} waveform={waveform} mock={mock} />
      )}
      {noTimes && (
        <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
          No audio timestamps: this run used the reference transcripts. The 20-second passage player appears with the speech-recognition run.
        </p>
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
              const played = !unavailable && t > 0 && pos <= t / total;
              return <span key={i} className={cn("flex-1 rounded-full", cited ? "bg-foreground" : played ? "bg-muted-foreground" : "bg-muted-foreground/35", cited && played && "opacity-60")}
                style={{ height: `${Math.max(8, v * 100)}%` }} />;
            })}
          </div>
        ) : (
          <div className="relative h-1.5 rounded-full bg-muted" aria-hidden>
            <div className="absolute inset-y-0 rounded-full bg-foreground/50" style={{ left: `${at(start) * 100}%`, width: `${(at(end) - at(start)) * 100}%` }} />
            <div className="player-progress absolute inset-y-0 left-0 rounded-full bg-foreground" style={{ width: `${(t / total) * 100}%` }} />
          </div>
        )}
        <div className="tabular mt-1 flex justify-between gap-2 text-[11px] text-muted-foreground">
          <span>{fmtTime(off + t)}</span>
          <span className="truncate">{unavailable && `${noAudio} · `}<span className="text-foreground">■</span> the cited words</span>
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
