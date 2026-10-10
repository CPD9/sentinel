"use client";
// SVG bodies of each lane. All lanes use the same Scale, so the same time is the same x everywhere.
import { SPEAKER_COLOR } from "@/lib/colors";
import type {
  AsrConfidence, AudioQuality, Contour, SpeechActivity, SpeechRate, Turns, WaveformPeaks,
} from "@/lib/types";
import { type Scale, xOf } from "./lane-frame";

const visible = (s: Scale, a: number, b: number) => b >= s.t0 && a <= s.t1;

export function WaveformBody({ data, scale, h }: { data: WaveformPeaks; scale: Scale; h: number }) {
  const mid = h / 2;
  const i0 = Math.max(0, Math.floor(scale.t0 / data.bucket_s) - 1);
  const i1 = Math.min(data.min.length, Math.ceil(scale.t1 / data.bucket_s) + 1);
  let d = "";
  for (let i = i0; i < i1; i++) {
    const x = xOf(scale, (i + 0.5) * data.bucket_s);
    d += `M${x.toFixed(1)} ${(mid - data.max[i] * (mid - 2)).toFixed(1)}V${(mid - data.min[i] * (mid - 2)).toFixed(1)}`;
  }
  const bw = Math.max(1, xOf(scale, data.bucket_s) - xOf(scale, 0));
  return (
    <g>
      <line x1={0} x2={scale.w} y1={mid} y2={mid} stroke="var(--grid)" />
      <path d={d} stroke="var(--trace)" strokeWidth={Math.min(bw, 3)} opacity={0.85} />
    </g>
  );
}

const ROLES = ["advisor", "customer", "unknown"] as const;
export function TurnsBody({ data, scale, h }: { data: Turns; scale: Scale; h: number }) {
  const roles = ROLES.filter((r) => r !== "unknown" || data.items.some((t) => t.speaker === "unknown"));
  const rowH = h / roles.length;
  return (
    <g>
      {roles.map((r, i) => (
        <g key={r}>
          <line x1={0} x2={scale.w} y1={(i + 1) * rowH} y2={(i + 1) * rowH} stroke="var(--grid)" />
          {data.items.filter((t) => t.speaker === r && visible(scale, t.start_s, t.end_s)).map((t, k) => (
            <rect key={k} x={xOf(scale, t.start_s)} width={Math.max(1, xOf(scale, t.end_s) - xOf(scale, t.start_s))} y={i * rowH + 3} height={rowH - 6} rx={2} fill={SPEAKER_COLOR[r]} opacity={0.9} />
          ))}
        </g>
      ))}
    </g>
  );
}
export const turnRoles = (data: Turns) => ROLES.filter((r) => r !== "unknown" || data.items.some((t) => t.speaker === "unknown"));

export function VadBody({ data, scale, h }: { data: SpeechActivity; scale: Scale; h: number }) {
  return (
    <g>
      {data.intervals.filter((iv) => visible(scale, iv.start_s, iv.end_s)).map((iv, k) => (
        <rect key={k} x={xOf(scale, iv.start_s)} width={Math.max(1, xOf(scale, iv.end_s) - xOf(scale, iv.start_s))} y={4} height={h - 8} fill="var(--trace)" opacity={0.55} />
      ))}
    </g>
  );
}

/** Domain of the avg-log-prob lane: [floor, 0]. Shared with the hover readout. */
export function logprobDomain(d: AsrConfidence): [number, number] {
  const m = Math.min(...d.segments.map((s) => s.avg_logprob), -0.5);
  return [Math.floor((m - 0.1) * 10) / 10, 0];
}

export function AsrBody({ data, scale, h }: { data: AsrConfidence; scale: Scale; h: number }) {
  const [lo, hi] = logprobDomain(data);
  const y = (v: number) => 4 + ((hi - v) / (hi - lo)) * (h - 8);
  const segs = data.segments.filter((s) => visible(scale, s.start_s, s.end_s));
  let path = "";
  segs.forEach((s, i) => {
    const x0 = xOf(scale, s.start_s), x1 = xOf(scale, s.end_s);
    const adjacent = i > 0 && s.start_s - segs[i - 1].end_s < 0.05; // step between touching segments, break at silences
    path += `${adjacent ? "L" : "M"}${x0.toFixed(1)} ${y(s.avg_logprob).toFixed(1)}H${x1.toFixed(1)}`;
  });
  return (
    <g>
      <defs>
        <pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="5" stroke="var(--review)" strokeWidth="2" />
        </pattern>
      </defs>
      <line x1={0} x2={scale.w} y1={y(0)} y2={y(0)} stroke="var(--grid)" />
      {/* hatched band: height = no-speech probability (0–1 of the lane height, from the bottom) */}
      {segs.map((s) => (
        <rect key={s.segment_id} x={xOf(scale, s.start_s)} width={Math.max(1, xOf(scale, s.end_s) - xOf(scale, s.start_s))}
          y={h - 4 - s.no_speech_prob * (h - 8)} height={Math.max(1, s.no_speech_prob * (h - 8))} fill="url(#hatch)" opacity={0.8} />
      ))}
      <path d={path} fill="none" stroke="var(--trace)" strokeWidth={2} />
    </g>
  );
}

export function QualityBody({ data, scale, h }: { data: AudioQuality; scale: Scale; h: number }) {
  const y = (v: number) => 4 + (1 - v) * (h - 8);
  return (
    <g>
      {data.segments.filter((s) => visible(scale, s.start_s, s.end_s)).map((s) => (
        <rect key={s.segment_id} x={xOf(scale, s.start_s)} width={Math.max(1, xOf(scale, s.end_s) - xOf(scale, s.start_s))} y={y(s.score)} height={h - 4 - y(s.score)} fill="var(--info)" opacity={0.55} stroke="var(--info)" />
      ))}
      <line x1={0} x2={scale.w} y1={y(1)} y2={y(1)} stroke="var(--grid)" />
    </g>
  );
}

export function ContourBody({ data, scale, h, color = "var(--trace)" }: { data: Contour; scale: Scale; h: number; color?: string }) {
  const vals = data.values.filter((v): v is number => v != null);
  const [lo, hi] = domain(vals);
  const y = (v: number) => 4 + (1 - (v - lo) / (hi - lo)) * (h - 8);
  // null = unvoiced / no estimate → a gap in the line, never zero
  let d = "", pen = false;
  data.times_s.forEach((t, i) => {
    const v = data.values[i];
    if (v == null || t < scale.t0 - 1 || t > scale.t1 + 1) { pen = false; return; }
    d += `${pen ? "L" : "M"}${xOf(scale, t).toFixed(1)} ${y(v).toFixed(1)}`;
    pen = true;
  });
  return <path d={d} fill="none" stroke={color} strokeWidth={1.5} />;
}
export function domain(vals: number[]): [number, number] {
  if (!vals.length) return [0, 1];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo || 1) * 0.08;
  return [lo - pad, hi + pad];
}

export function RateBody({ data, scale, h }: { data: SpeechRate; scale: Scale; h: number }) {
  const [lo, hi] = domain(data.points.map((p) => p.value));
  const y = (v: number) => 4 + (1 - (v - lo) / (hi - lo)) * (h - 8);
  return (
    <g>
      {data.points.filter((p) => visible(scale, p.start_s, p.end_s)).map((p, k) => (
        <line key={k} x1={xOf(scale, p.start_s)} x2={xOf(scale, p.end_s)} y1={y(p.value)} y2={y(p.value)} stroke={SPEAKER_COLOR[p.speaker]} strokeWidth={3} strokeLinecap="round" />
      ))}
    </g>
  );
}
