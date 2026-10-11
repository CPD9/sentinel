"use client";
// Stacked lanes on ONE shared time axis (docs/PRODUCT.md §3.4). Waveform / heat-map / card visual language follows
// audio-cnn-visualisation (MIT, © 2025 Andreas Trolle); the shared-axis stack, evidence windows and synchronised playhead are ours.
import { Pause, Play, Repeat, ZoomIn, ZoomOut } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CriterionChip, SpeakerChip } from "@/components/shell/badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useCallAudio } from "@/components/call/audio-context";
import { criterionColor, CRITERION_LABEL } from "@/lib/colors";
import { fmtRange, fmtTime, humanize, pct } from "@/lib/format";
import type { AnalysisArtifact, CallResult, EvidenceWindow } from "@/lib/types";
import { VerticalColorBar } from "./color-bar";
import { FeatureMapsSection } from "./feature-maps";
import { AsrBody, ContourBody, domain, logprobDomain, QualityBody, RateBody, turnRoles, TurnsBody, VadBody, WaveformBody } from "./lane-content";
import { clamp, Lane, LABEL_W, RIGHT_W, tOf, TimeAxis, useWidth, xOf, type Scale } from "./lane-frame";
import { MelCanvas } from "./mel-canvas";

const MIN_SPAN = 3;
const AXIS_H = 38;
const GAP = 8;

const hz = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${Math.round(v)}`);
const winKey = (w: EvidenceWindow) => `${w.finding_index}.${w.evidence_index}`;

export function AudioLanes({ a, result, initialWindow }: { a: AnalysisArtifact; result: CallResult; initialWindow?: string }) {
  const dur = a.duration_s;
  const audio = useCallAudio();
  const [outerRef, outerW] = useWidth<HTMLDivElement>();
  const [view, setView] = useState(() => {
    const w = initialWindow ? a.evidence_windows.find((x) => winKey(x) === initialWindow) : undefined;
    if (!w) return { t0: 0, t1: dur };
    const pad = Math.max(8, (w.end_s - w.start_s) * 0.6);
    const t0 = clamp(w.start_s - pad, 0, Math.max(0, dur - MIN_SPAN));
    return { t0, t1: Math.min(dur, Math.max(t0 + MIN_SPAN, w.end_s + pad)) };
  });
  const [selected, setSelected] = useState<string | null>(initialWindow ?? null);
  const [hover, setHover] = useState<number | null>(null);
  const [optional, setOptional] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);

  // never wait forever on a narrow screen: once measured, draw at least at the lanes' minimum width (they scroll)
  const plotW = outerW <= 0 ? 0 : Math.max(760 - LABEL_W - RIGHT_W, outerW - LABEL_W - RIGHT_W);
  const scale: Scale = { t0: view.t0, t1: view.t1, w: plotW };
  const span = view.t1 - view.t0;

  const setClamped = useCallback((t0: number, t1: number) => {
    const s = clamp(t1 - t0, Math.min(MIN_SPAN, dur), dur);
    const a0 = clamp(t0, 0, dur - s);
    setView({ t0: a0, t1: a0 + s });
  }, [dur]);
  const zoomAround = useCallback((factor: number, center: number) => {
    const s = clamp((view.t1 - view.t0) * factor, Math.min(MIN_SPAN, dur), dur);
    const f = (center - view.t0) / (view.t1 - view.t0);
    setClamped(center - f * s, center - f * s + s);
  }, [view, dur, setClamped]);

  // ctrl/⌘ + wheel = zoom at the pointer; horizontal wheel / shift+wheel = pan. Plain vertical wheel scrolls the page.
  useEffect(() => {
    const el = overlayRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const rect = el.getBoundingClientRect();
      const t = tOf(scale, e.clientX - rect.left);
      if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoomAround(e.deltaY > 0 ? 1.25 : 0.8, t); }
      else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) { e.preventDefault(); const d = ((e.deltaX || e.deltaY) / Math.max(1, scale.w)) * span; setClamped(view.t0 + d, view.t1 + d); }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  // Follow the playhead during playback.
  useEffect(() => {
    if (!audio.playing || (audio.time <= view.t1 && audio.time >= view.t0)) return;
    const raf = requestAnimationFrame(() => setClamped(audio.time - span * 0.15, audio.time + span * 0.85));
    return () => cancelAnimationFrame(raf);
  }, [audio.playing, audio.time, view, span, setClamped]);

  const selectedWin = a.evidence_windows.find((w) => winKey(w) === selected) ?? null;

  // lane list
  const hasMel = !!a.mel_spectrogram;
  const mel = a.mel_spectrogram;
  const heights = { wave: 70, mel: 150, turns: 54, vad: 24, asr: 84, q: 84, opt: 64 };
  const roles = a.turns ? turnRoles(a.turns) : [];
  const stackH = (a.waveform_peaks ? heights.wave + GAP : 0) + (hasMel ? heights.mel + GAP : 0) + (a.turns ? heights.turns + GAP : 0) +
    (a.speech_activity ? heights.vad + GAP : 0) + (a.asr_confidence ? heights.asr + GAP : 0) + (a.audio_quality ? heights.q + GAP : 0) +
    (optional ? [a.pitch, a.energy, a.speech_rate].filter(Boolean).length * (heights.opt + GAP) : 0);

  const onOverlayClick = (e: React.MouseEvent) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const t = clamp(tOf(scale, e.clientX - rect.left), 0, dur);
    const hits = a.evidence_windows.filter((w) => t >= w.start_s && t <= w.end_s).sort((x, y) => (x.end_s - x.start_s) - (y.end_s - y.start_s));
    if (hits[0]) setSelected(winKey(hits[0]));
    audio.seek(t);
  };

  const onPlayPause = () => {
    if (audio.playing) { audio.pause(); return; }
    const inside = selectedWin && audio.time >= selectedWin.start_s && audio.time <= selectedWin.end_s;
    if (selectedWin && (inside || audio.time < selectedWin.start_s - 0.01)) audio.play(inside ? audio.time : selectedWin.start_s, { start: selectedWin.start_s, end: selectedWin.end_s });
    else audio.play(undefined, null);
  };

  const readout = useMemo(() => (hover == null ? null : readoutAt(a, hover)), [a, hover]);
  const ht = hover;

  if (plotW <= 0) return <div ref={outerRef} className="skeleton h-96" aria-busy="true" />;


  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
      <div ref={outerRef} className="min-w-[760px] space-y-3">
        {/* transport + zoom */}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={onPlayPause} disabled={!audio.available} aria-label={audio.playing ? "Pause" : "Play"}>
            {audio.playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}{audio.playing ? "Pause" : "Play"}
          </Button>
          <span className="tabular text-sm" aria-live="off">{fmtTime(audio.time, true)} / {fmtTime(dur)}</span>
          {audio.loop && <Badge className="border-info text-info"><Repeat className="size-3" />looping window</Badge>}
          {!audio.available && <span className="text-xs text-muted-foreground">Playback disabled ({audio.error}). Click a lane to place the cursor.</span>}
          <div className="ml-auto flex items-center gap-1">
            <Button variant="outline" size="icon" aria-label="Zoom out" onClick={() => zoomAround(1.6, (view.t0 + view.t1) / 2)}><ZoomOut className="size-4" /></Button>
            <Button variant="outline" size="icon" aria-label="Zoom in" onClick={() => zoomAround(0.625, (view.t0 + view.t1) / 2)}><ZoomIn className="size-4" /></Button>
            <Button variant="outline" size="sm" onClick={() => setClamped(0, dur)}>Fit</Button>
            <Button variant="outline" size="sm" disabled={!selectedWin} onClick={() => selectedWin && setClamped(selectedWin.start_s - 6, selectedWin.end_s + 6)}>Zoom to window</Button>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <label className="flex flex-1 items-center gap-2">view {fmtTime(view.t0)}–{fmtTime(view.t1)}
            <input type="range" aria-label="Pan the time axis" className="flex-1" min={0} max={Math.max(0, dur - span)} step={0.1} value={view.t0} disabled={span >= dur - 0.01}
              onChange={(e) => setClamped(+e.target.value, +e.target.value + span)} />
          </label>
          <span className="hidden md:inline">ctrl/⌘ + scroll = zoom · shift + scroll = pan</span>
        </div>
        <p className="min-h-5 text-xs text-muted-foreground" aria-live="polite">
          {readout ? <><b className="tabular text-foreground">{fmtTime(ht, true)}</b> · {readout}</> : "Hover a lane to read the values at that time. Click to place the playhead; click a shaded window to select it."}
        </p>

        {/* the stack */}
        <div className="relative" style={{ paddingBottom: 0 }}>
          <div className="space-y-2">
            {a.waveform_peaks && (
              <Lane title="Waveform" axes={a.waveform_peaks.axes} axis="y" height={heights.wave} scale={scale}
                ticks={[{ y: 0, label: "+1" }, { y: heights.wave / 2, label: "0" }, { y: heights.wave, label: "−1" }]}>
                <WaveformBody data={a.waveform_peaks} scale={scale} h={heights.wave} />
              </Lane>
            )}
            {mel && (
              <Lane title="Mel spectrogram" axes={mel.axes} axis="y" height={heights.mel} scale={scale} raw
                ticks={[0, 0.5, 1].map((f) => ({ y: (1 - f) * heights.mel, label: hz(mel.freqs_hz[Math.round(f * (mel.freqs_hz.length - 1))]) }))}
                right={<VerticalColorBar min={mel.db_min} max={mel.db_max} label={mel.axes.value?.label ?? "level"} unit={mel.axes.value?.unit ?? "dB"} height={heights.mel} />}>
                <MelCanvas mel={mel} scale={scale} height={heights.mel} />
              </Lane>
            )}
            {a.turns && (
              <Lane title="Speakers" height={heights.turns} scale={scale} ticks={roles.map((r, i) => ({ y: (i + 0.5) * (heights.turns / roles.length), label: r.slice(0, 3) }))}>
                <TurnsBody data={a.turns} scale={scale} h={heights.turns} />
              </Lane>
            )}
            {a.speech_activity && (
              <Lane title="Speech activity (VAD)" height={heights.vad} scale={scale}><VadBody data={a.speech_activity} scale={scale} h={heights.vad} /></Lane>
            )}
            {a.asr_confidence && (() => { const [lo] = logprobDomain(a.asr_confidence); return (
              <Lane title="ASR confidence" axes={a.asr_confidence.axes} axis="value" height={heights.asr} scale={scale}
                note="hatched = no-speech prob. (0–1, bar height)" ticks={[{ y: 4, label: "0" }, { y: heights.asr - 4, label: lo.toFixed(1) }]}>
                <AsrBody data={a.asr_confidence} scale={scale} h={heights.asr} />
              </Lane>); })()}
            {a.audio_quality && (
              <Lane title="Audio quality" axes={a.audio_quality.axes} axis="value" height={heights.q} scale={scale}
                badge={<Badge className="border-info text-info" title="Only this lane feeds the decision">call {a.audio_quality.call_score.toFixed(2)} · {a.audio_quality.call_snr_db.toFixed(0)} dB SNR</Badge>}
                note="feeds confidence gate" ticks={[{ y: 4, label: "1" }, { y: heights.q - 4, label: "0" }]}>
                <QualityBody data={a.audio_quality} scale={scale} h={heights.q} />
              </Lane>
            )}
            {optional && a.pitch && <ContourLane title="Pitch (F0)" c={a.pitch} scale={scale} h={heights.opt} />}
            {optional && a.energy && <ContourLane title="Energy" c={a.energy} scale={scale} h={heights.opt} />}
            {optional && a.speech_rate && (() => { const [lo, hi] = domain(a.speech_rate.points.map((p) => p.value)); return (
              <Lane title="Speech rate" axes={a.speech_rate.axes} axis="value" height={heights.opt} scale={scale} ticks={[{ y: 4, label: hi.toFixed(0) }, { y: heights.opt - 4, label: lo.toFixed(0) }]}>
                <RateBody data={a.speech_rate} scale={scale} h={heights.opt} />
              </Lane>); })()}
          </div>
          <div style={{ marginTop: GAP }}><TimeAxis scale={scale} axes={(a.waveform_peaks ?? a.mel_spectrogram ?? a.audio_quality ?? a.asr_confidence ?? a.turns ?? a.speech_activity)?.axes} /></div>

          {/* overlay: evidence windows, playhead, hover cursor, pointer input — one layer over every lane */}
          <div ref={overlayRef} className="absolute top-0 cursor-crosshair" style={{ left: LABEL_W, width: plotW, height: stackH - GAP }}
            onClick={onOverlayClick} onMouseMove={(e) => setHover(clamp(tOf(scale, e.clientX - e.currentTarget.getBoundingClientRect().left), 0, dur))} onMouseLeave={() => setHover(null)}>
            {a.evidence_windows.map((w) => {
              const x0 = clamp(xOf(scale, w.start_s), 0, plotW), x1 = clamp(xOf(scale, w.end_s), 0, plotW);
              if (x1 <= 0 || x0 >= plotW || x1 - x0 < 1) return null;
              const sel = winKey(w) === selected;
              const col = criterionColor(w.criterion);
              return (
                <div key={winKey(w)} className="pointer-events-none absolute inset-y-0"
                  style={{ left: x0, width: x1 - x0, background: `color-mix(in srgb, ${col} ${sel ? 30 : 17}%, transparent)`, borderLeft: `${sel ? 2 : 1}px solid ${col}`, borderRight: `${sel ? 2 : 1}px solid ${col}`, boxShadow: sel ? `0 0 0 1px ${col}` : undefined }}>
                  {x1 - x0 > 46 && <span className="pointer-events-none absolute left-0 top-0 max-w-full truncate px-1 text-[10px] font-semibold leading-4" style={{ color: "var(--foreground)", background: `color-mix(in srgb, ${col} 35%, var(--card))` }}>{CRITERION_LABEL[w.criterion]}</span>}
                </div>
              );
            })}
            {ht != null && ht >= view.t0 && ht <= view.t1 && <div className="pointer-events-none absolute inset-y-0 w-px bg-foreground/40" style={{ left: xOf(scale, ht) }} />}
            {audio.time >= view.t0 && audio.time <= view.t1 && (
              <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-alarm" style={{ left: xOf(scale, audio.time) - 1 }} aria-hidden>
                <div className="absolute -top-1 -left-[3px] size-2 rounded-full bg-alarm" />
              </div>
            )}
          </div>
        </div>

        {/* window chips (keyboard-accessible selection) */}
        {a.evidence_windows.length > 0 && (
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Evidence windows">
            <span className="text-xs text-muted-foreground">Evidence windows:</span>
            {a.evidence_windows.map((w) => (
              <button key={winKey(w)} type="button" aria-pressed={winKey(w) === selected}
                onClick={() => { setSelected(winKey(w) === selected ? null : winKey(w)); audio.seek(w.start_s); }}
                className={`rounded-md border px-2 py-0.5 text-xs ${winKey(w) === selected ? "border-foreground bg-muted font-semibold" : "border-border"}`}>
                <span className="mr-1 inline-block size-2 rounded-full" style={{ background: criterionColor(w.criterion) }} />{humanize(w.criterion)} {fmtRange(w.start_s, w.end_s)}
              </button>
            ))}
          </div>
        )}

        {/* legend for speaker colours */}
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><i className="inline-block size-2.5 rounded-sm" style={{ background: "var(--advisor)" }} />advisor</span>
          <span className="flex items-center gap-1"><i className="inline-block size-2.5 rounded-sm" style={{ background: "var(--customer)" }} />customer</span>
          <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-4 rounded-sm bg-alarm" />playhead</span>
          <Button variant="ghost" size="sm" className="ml-auto h-6" onClick={() => setOptional((o) => !o)} aria-expanded={optional}>
            {optional ? "Hide" : "Show"} pitch, energy, speech rate
          </Button>
        </div>
      </div>
      </div>

      {selectedWin && <WindowDetails w={selectedWin} result={result} />}

      <MissingBlocks a={a} />
      <FeatureMapsSection a={a} />
    </div>
  );
}

function ContourLane({ title, c, scale, h }: { title: string; c: NonNullable<AnalysisArtifact["pitch"]>; scale: Scale; h: number }) {
  const [lo, hi] = domain(c.values.filter((v): v is number => v != null));
  return (
    <Lane title={title} axes={c.axes} axis="value" height={h} scale={scale} note={title.startsWith("Pitch") ? "gaps = unvoiced" : undefined} ticks={[{ y: 4, label: hi.toFixed(0) }, { y: h - 4, label: lo.toFixed(0) }]}>
      <ContourBody data={c} scale={scale} h={h} />
    </Lane>
  );
}

/** A null block hides its lane and shows one line; the stage error text is used when it names the block. */
function MissingBlocks({ a }: { a: AnalysisArtifact }) {
  const blocks: [string, unknown][] = [
    ["waveform_peaks", a.waveform_peaks], ["mel_spectrogram", a.mel_spectrogram], ["turns", a.turns], ["speech_activity", a.speech_activity],
    ["asr_confidence", a.asr_confidence], ["audio_quality", a.audio_quality], ["pitch", a.pitch], ["energy", a.energy], ["speech_rate", a.speech_rate],
  ];
  const missing = blocks.filter(([, v]) => v == null);
  if (!missing.length && !a.stage_errors.length) return null;
  return (
    <ul className="space-y-1 text-xs text-muted-foreground" aria-label="Lanes not shown">
      {missing.map(([name]) => {
        const err = a.stage_errors.find((e) => e.stage.endsWith(name) || e.stage.includes(name));
        return <li key={name}><b className="font-mono text-foreground">{name}</b>: {err ? <span className="text-alarm">failed — {err.message}</span> : "not computed for this call"}</li>;
      })}
    </ul>
  );
}

function WindowDetails({ w, result }: { w: EvidenceWindow; result: CallResult }) {
  const audio = useCallAudio();
  const f = result.findings[w.finding_index];
  const e = f?.evidence[w.evidence_index];
  return (
    <Card>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <CriterionChip criterion={w.criterion} />
          <span className="tabular text-sm">{fmtRange(w.start_s, w.end_s)}</span>
          {e && <SpeakerChip speaker={e.speaker} />}
          {f && <span className="tabular text-xs text-muted-foreground">finding risk {pct(f.risk)}</span>}
        </div>
        {e && <blockquote lang="gsw" className="border-l-2 border-foreground/60 pl-3 text-sm">“{e.text}”</blockquote>}
        <div className="flex flex-wrap gap-3 text-xs">
          <Button size="sm" variant="outline" disabled={!audio.available} onClick={() => audio.play(w.start_s, { start: w.start_s, end: w.end_s })}><Repeat className="size-3.5" />Play window (loop)</Button>
          <Link className="self-center underline underline-offset-2" href={`/calls/${result.call_id}#passages`}>Open evidence card</Link>
          {e && <Link className="self-center underline underline-offset-2" href={`/calls/${result.call_id}?tab=transcript&seg=${e.segment_ids.join(",")}`}>Jump to transcript</Link>}
        </div>
      </CardContent>
    </Card>
  );
}

/** Text readout of every lane at time t (the overlay swallows native tooltips). */
function readoutAt(a: AnalysisArtifact, t: number): string {
  const at = <T extends { start_s: number; end_s: number }>(xs: T[] | undefined) => xs?.find((x) => t >= x.start_s && t < x.end_s);
  const parts: string[] = [];
  const turn = at(a.turns?.items); if (turn) parts.push(`speaker ${turn.speaker}`);
  if (a.speech_activity) parts.push(at(a.speech_activity.intervals) ? "speech" : "no speech");
  const asr = at(a.asr_confidence?.segments); if (asr) parts.push(`${asr.segment_id} log-prob ${asr.avg_logprob.toFixed(2)}, no-speech ${pct(asr.no_speech_prob)}`);
  const q = at(a.audio_quality?.segments); if (q) parts.push(`quality ${q.score.toFixed(2)} (SNR ${q.snr_db.toFixed(0)} dB)`);
  const near = (c: AnalysisArtifact["pitch"]) => { if (!c) return null; let bi = 0; c.times_s.forEach((x, i) => { if (Math.abs(x - t) < Math.abs(c.times_s[bi] - t)) bi = i; }); return c.values[bi]; };
  const p = near(a.pitch); if (a.pitch) parts.push(p == null ? "pitch: unvoiced" : `pitch ${p.toFixed(0)} ${a.pitch.axes.value?.unit ?? ""}`);
  const en = near(a.energy); if (en != null && a.energy) parts.push(`energy ${en.toFixed(0)} ${a.energy.axes.value?.unit ?? ""}`);
  const w = a.evidence_windows.find((x) => t >= x.start_s && t <= x.end_s); if (w) parts.push(`in window: ${humanize(w.criterion)}`);
  return parts.join(" · ");
}
