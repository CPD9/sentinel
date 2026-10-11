"use client";
// Risk and confidence as gradient bars with a marker for "where this call stands".
//   risk        grey → amber → red, the colour stops sit on the real review and alarm thresholds (they move when the
//               thresholds move in Sensitivity), so both pages tell the same story.
//   confidence  amber below the gate (that is what sends a call to review) → calm slate above it.
// No green on purpose: in compliance green reads as "cleared", and high confidence only means the system trusts its verdict.
// Colour is never alone: the marker position, the threshold ticks and the caption (hover title / screen reader) say the same.
import { InfoTip } from "@/components/ui/info-tip";
import type { Term } from "@/lib/glossary";
import { pct } from "@/lib/format";

const GREY = "color-mix(in srgb, var(--noalert) 55%, var(--card))";
const SLATE = "color-mix(in srgb, var(--foreground) 55%, var(--card))";
const SOFT = 4; // % blend on each side of a threshold, so the gradient reads as a gradient but the zones stay clear
const clampPct = (x: number) => Math.min(100, Math.max(0, x));

function stops(parts: [string, number, number][]): string {
  return `linear-gradient(to right, ${parts.map(([c, a, b]) => `${c} ${clampPct(a)}% ${clampPct(b)}%`).join(", ")})`;
}

function Gauge({ label, term, value, gradient, marker, ticks, caption, compact }: {
  label: string; term: Term; value: number | null; gradient: string; marker: string; caption: string;
  ticks: { at: number; label: string }[]; compact?: boolean;
}) {
  const v = value == null ? null : Math.min(1, Math.max(0, value));
  const h = compact ? "h-1.5" : "h-2";
  return (
    <div className={compact ? "w-36" : undefined}>
      <div className={`flex items-center justify-between gap-2 ${compact ? "text-xs" : "text-sm"}`}>
        <span className="flex items-center gap-0.5 text-muted-foreground">{label}<InfoTip term={term} /></span>
        <span className={`tabular font-semibold ${compact ? "text-sm" : ""}`}>{v == null ? "n/a" : pct(v)}</span>
      </div>
      <div title={caption} className={`relative mt-1.5 ${h}`} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1}
        aria-valuenow={value ?? undefined} aria-valuetext={`${v == null ? "not available" : pct(v)}, ${caption}`}>
        {/* the whole scale, faint */}
        <div className="absolute inset-0 rounded-full opacity-25" style={{ background: gradient }} />
        {v != null && (
          <>
            {/* the part up to this call's value, in full colour (the inner layer keeps the track's width so colours stay in place) */}
            <div className="gauge-fill absolute inset-y-0 left-0 overflow-hidden rounded-full" style={{ width: `${v * 100}%` }}>
              <div className="absolute inset-y-0 left-0" style={{ width: v > 0 ? `${100 / v}%` : "0", background: gradient }} />
            </div>
          </>
        )}
        {ticks.map((t) => (
          <span key={t.label} aria-hidden className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground/55" style={{ left: `${t.at * 100}%` }} />
        ))}
        {v != null && (
          <span aria-hidden className={`gauge-marker absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-card ${compact ? "size-3" : "size-3.5"}`}
            style={{ left: `${v * 100}%`, borderColor: marker }} />
        )}
      </div>
      {!compact && caption && <p className="mt-1 text-xs text-muted-foreground">{caption}</p>}
    </div>
  );
}

export function RiskGauge({ value, review, alarm, compact }: { value: number | null; review?: number; alarm?: number; compact?: boolean }) {
  const r = (review ?? 0.4) * 100, a = (alarm ?? 0.7) * 100;
  const gradient = stops([[GREY, 0, r - SOFT], ["var(--gauge-review)", r + SOFT, a - SOFT], ["var(--gauge-alarm)", a + SOFT, 100]]);
  const known = review != null && alarm != null;
  const zone = value == null || !known ? null : value >= alarm! ? "alarm" : value >= review! ? "review" : "low";
  const marker = zone === "alarm" ? "var(--gauge-alarm)" : zone === "review" ? "var(--gauge-review)" : "var(--noalert)";
  const caption = zone === "alarm" ? "at or above the alarm threshold" : zone === "review" ? "between the review and the alarm threshold"
    : zone === "low" ? "below the review threshold" : "";
  const ticks = known ? [{ at: review!, label: "review threshold" }, { at: alarm!, label: "alarm threshold" }] : [];
  return <Gauge label="Risk" term="risk" value={value} gradient={gradient} marker={marker} ticks={ticks} caption={caption} compact={compact} />;
}

export function ConfidenceGauge({ value, gate, compact }: { value: number | null; gate?: number; compact?: boolean }) {
  const g = (gate ?? 0.5) * 100;
  const gradient = stops([["var(--gauge-review)", 0, g - SOFT], [SLATE, g + SOFT, 100]]);
  const below = value != null && gate != null && value < gate;
  const caption = value == null ? "not computed (a processing step failed)" : below ? "below the gate: a person decides" : gate != null ? "above the gate" : "";
  return <Gauge label="Confidence" term="confidence" value={value} gradient={gradient} marker={below ? "var(--gauge-review)" : "var(--foreground)"}
    ticks={gate != null ? [{ at: gate, label: "confidence gate" }] : []} caption={caption} compact={compact} />;
}
