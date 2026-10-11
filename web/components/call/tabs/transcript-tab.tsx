"use client";
import { Pause, Play, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { DocGate, EmptyState } from "@/components/shell/states";
import { Select } from "@/components/ui/select";
import { useCallAudio } from "../audio-context";
import { criterionColor, SPEAKER_COLOR } from "@/lib/colors";
import { speakerLabel } from "@/lib/explain";
import { fmtTime, humanize } from "@/lib/format";
import { ASR_HIGH_NO_SPEECH, ASR_LOW_LOGPROB } from "@/lib/tabs";
import type { CallResult, DecisionTrace, Fact, KeywordHit, Transcript, TranscriptSegment } from "@/lib/types";
import type { Loadable } from "@/lib/use-async";
import { cn } from "@/lib/utils";

export function TranscriptTab({ result, trace, transcript, focusSeg }: {
  result: CallResult; trace: Loadable<DecisionTrace>; transcript: Loadable<Transcript>; focusSeg?: string;
}) {
  return (
    <DocGate state={transcript} unavailable="Transcript not available (ASR failed or not run).">
      {(t) => <Body result={result} hits={trace.data?.keyword_hits ?? []} facts={trace.data?.facts ?? []} t={t} focusSeg={focusSeg} />}
    </DocGate>
  );
}

function Body({ result, hits, facts, t, focusSeg }: { result: CallResult; hits: KeywordHit[]; facts: Fact[]; t: Transcript; focusSeg?: string }) {
  const audio = useCallAudio();
  const [q, setQ] = useState("");
  const [speaker, setSpeaker] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const focus = useMemo(() => new Set((focusSeg ?? "").split(",").filter(Boolean)), [focusSeg]);
  const firstFocus = useRef<HTMLLIElement | null>(null);

  // segment id → criterion colour for evidence, set for counter-evidence
  const evidence = useMemo(() => {
    const m = new Map<string, string>(), c = new Set<string>();
    for (const f of result.findings) {
      f.evidence.forEach((e) => e.segment_ids.forEach((id) => m.set(id, f.criterion)));
      f.counter_evidence.forEach((e) => e.segment_ids.forEach((id) => c.add(id)));
    }
    return { m, c };
  }, [result]);
  // segment id → Standard German gloss of the (valid) fact quoted there; segments cited by any valid fact
  const { gloss, factSegs } = useMemo(() => {
    const g = new Map<string, string>(), fs = new Set<string>();
    for (const f of facts) {
      if (!f.valid) continue;
      f.segment_ids.forEach((id) => fs.add(id));
      if (f.gloss_de && f.segment_ids[0] && !g.has(f.segment_ids[0])) g.set(f.segment_ids[0], f.gloss_de);
    }
    return { gloss: g, factSegs: fs };
  }, [facts]);
  const hitsBySeg = useMemo(() => {
    const m = new Map<string, KeywordHit[]>();
    hits.forEach((h) => m.set(h.segment_id, [...(m.get(h.segment_id) ?? []), h]));
    return m;
  }, [hits]);

  useEffect(() => { firstFocus.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [focusSeg, t]);

  if (t.segments.length === 0) return <EmptyState>No speech recognised.</EmptyState>;
  const rows = t.segments.filter((s) => (!speaker || s.speaker === speaker) && (!q || s.text.toLowerCase().includes(q.toLowerCase())));
  const firstFocusId = rows.find((s) => focus.has(s.id))?.id;

  const playingId = audio.playing ? t.segments.find((x) => x.start_s != null && audio.time >= x.start_s && audio.time < (x.end_s ?? x.start_s + 1))?.id ?? null : null;
  const onPlay = (s: TranscriptSegment) => {
    if (playingId === s.id) { audio.pause(); return; }
    if (s.start_s == null) { setNote("No timestamp on this line: the run used the reference transcript, so there is no audio position to jump to."); return; }
    if (!audio.available) { setNote(audio.error ?? "Audio is not available."); return; }
    setNote(null);
    audio.play(s.start_s, null);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative">
          <Search className="pointer-events-none absolute left-2 top-2 size-4 text-muted-foreground" aria-hidden />
          <input type="search" aria-label="Search transcript" placeholder="Search transcript" value={q} onChange={(e) => setQ(e.target.value)}
            className="h-8 w-56 rounded-md border border-border bg-card pl-8 pr-2 text-sm" />
        </label>
        <Select label="Speaker" value={speaker} onChange={(e) => setSpeaker(e.target.value)}>
          <option value="">all</option><option value="advisor">Advisor</option><option value="customer">Customer</option><option value="unknown">Speaker (role unknown)</option>
        </Select>
        <p className="ml-auto text-xs text-muted-foreground">
          {t.mode === "reference" ? "Reference transcript (organiser script)" : `ASR${t.asr_model ? ` · ${t.asr_model}` : ""}`}
        </p>
      </div>
      <p className="text-xs text-muted-foreground" title={`Dimmed = avg log-prob < ${ASR_LOW_LOGPROB} or no-speech > ${Math.round(ASR_HIGH_NO_SPEECH * 100)} % (display heuristic only)`}>
        Tinted = evidence for a finding · bold = quoted by a fact (Standard German gloss on the right) · dotted box = keyword · grey underline = counter-evidence · dimmed = unclear speech recognition.
      </p>
      {note && <p role="status" className="rounded-md border border-border bg-muted px-3 py-2 text-xs">{note}</p>}
      {rows.length === 0 ? <EmptyState>No segment matches this search.</EmptyState> : (
        <ol className="divide-y divide-border rounded-lg border border-border bg-card">
          {rows.map((s) => {
            const crit = evidence.m.get(s.id);
            const counter = evidence.c.has(s.id);
            const lowConf = (s.avg_logprob != null && s.avg_logprob < ASR_LOW_LOGPROB) || (s.no_speech_prob != null && s.no_speech_prob > ASR_HIGH_NO_SPEECH);
            const isFocus = focus.has(s.id);
            const g = gloss.get(s.id);
            const quoted = factSegs.has(s.id);
            const ref = s.id === firstFocusId ? firstFocus : undefined;
            return (
              <li key={`${s.id}-${isFocus ? focusSeg : ""}`} ref={ref} id={`seg-${s.id}`} aria-current={playingId === s.id ? "true" : undefined}
                className={cn("flex gap-3 px-3 py-2.5 transition-colors duration-[var(--dur-fast)]", isFocus && "jumped ring-2 ring-inset ring-ring", playingId === s.id && "ring-2 ring-inset ring-foreground/60")}
                style={{ borderLeft: `4px solid ${SPEAKER_COLOR[s.speaker]}`, background: crit ? `color-mix(in srgb, ${criterionColor(crit)} 14%, transparent)` : undefined }}>
                <button type="button" onClick={() => onPlay(s)} aria-pressed={playingId === s.id}
                  className={cn("tabular flex w-16 shrink-0 items-start gap-1 text-left text-xs hover:text-foreground", playingId === s.id ? "font-semibold text-foreground" : "text-muted-foreground")}
                  aria-label={playingId === s.id ? `Pause at ${fmtTime(s.start_s)}` : `Play from ${fmtTime(s.start_s)}`}>
                  {playingId === s.id ? <Pause className="mt-0.5 size-3" /> : <Play className="mt-0.5 size-3" />}{s.start_s == null ? s.id : fmtTime(s.start_s)}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="mb-0.5 flex items-center gap-2"><span className="text-xs font-semibold" style={{ color: SPEAKER_COLOR[s.speaker] }}>{speakerLabel(s.speaker)}</span>
                    {crit && <span className="text-[11px] font-medium" style={{ color: criterionColor(crit) }}>evidence · {humanize(crit)}</span>}
                    {quoted && !crit && <span className="text-[11px] font-medium">quoted by a fact</span>}
                    {counter && <span className="text-[11px] text-muted-foreground">counter-evidence</span>}
                    {lowConf && <span className="text-[11px] text-muted-foreground" title={`avg log-prob ${s.avg_logprob}, no-speech ${s.no_speech_prob}`}>unclear speech recognition</span>}
                  </div>
                  <div className={cn("grid gap-x-6", g && "md:grid-cols-2")}>
                    <p lang="gsw" className={cn("text-body leading-relaxed", quoted && "font-semibold", lowConf && "text-muted-foreground underline decoration-dotted decoration-1 underline-offset-4", counter && "underline decoration-muted-foreground decoration-2 underline-offset-4")}>
                      <Highlighted text={s.text} hits={hitsBySeg.get(s.id) ?? []} />
                    </p>
                    {g && <p lang="de" className="text-body leading-relaxed text-muted-foreground"><span className="sr-only">Standard German: </span>{g}</p>}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/** Underlines each keyword hit's matched text inside the segment text; hover for family, term and score. */
function Highlighted({ text, hits }: { text: string; hits: KeywordHit[] }) {
  const spans: { start: number; end: number; hit: KeywordHit }[] = [];
  for (const h of hits) {
    const i = text.toLowerCase().indexOf(h.matched_text.toLowerCase());
    if (i >= 0 && !spans.some((s) => i < s.end && i + h.matched_text.length > s.start)) spans.push({ start: i, end: i + h.matched_text.length, hit: h });
  }
  spans.sort((a, b) => a.start - b.start);
  const out: React.ReactNode[] = [];
  let at = 0;
  spans.forEach((s, k) => {
    if (s.start > at) out.push(text.slice(at, s.start));
    out.push(
      <mark key={k} className="rounded-sm bg-transparent text-inherit underline decoration-dotted decoration-2 underline-offset-4 outline outline-1 outline-border"
        title={`keyword family: ${s.hit.family} · term: ${s.hit.term} · score ${s.hit.score.toFixed(2)}`}>{text.slice(s.start, s.end)}</mark>,
    );
    at = s.end;
  });
  out.push(text.slice(at));
  return <>{out}</>;
}
