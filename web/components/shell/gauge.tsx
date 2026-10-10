"use client";
// Risk and confidence as labelled bars. Colour carries meaning, never alone (a caption says the same in words):
//   risk        grey below the review threshold · amber in the review band · red at or above the alarm threshold
//   confidence  neutral above the gate · amber below it (that is what sends a call to review). No green on purpose:
//               in compliance green reads as "cleared", and high confidence only means the system trusts its verdict.
import { InfoTip } from "@/components/ui/info-tip";
import type { Term } from "@/lib/glossary";
import { pct } from "@/lib/format";

function Gauge({ label, term, value, color, ticks, caption }: {
  label: string; term: Term; value: number | null; color: string; caption: string; ticks: { at: number; label: string }[];
}) {
  const v = value == null ? 0 : Math.min(1, Math.max(0, value));
  return (
    <div>
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-1 text-muted-foreground">{label}<InfoTip term={term} /></span>
        <span className="tabular font-semibold">{value == null ? "n/a" : pct(value)}</span>
      </div>
      <div className="relative mt-1.5 h-2 rounded-full bg-muted" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={value ?? undefined} aria-valuetext={`${value == null ? "not available" : pct(value)}, ${caption}`}>
        {value != null && <div className="gauge-fill absolute inset-y-0 left-0 rounded-full" style={{ width: `${v * 100}%`, background: color }} />}
        {ticks.map((t) => (
          <span key={t.label} title={`${t.label} ${pct(t.at)}`} aria-hidden className="absolute -top-1 h-4 w-0.5 -translate-x-1/2 rounded-full bg-foreground/70" style={{ left: `${t.at * 100}%` }} />
        ))}
      </div>
      {caption && <p className="mt-1 text-xs text-muted-foreground">{caption}</p>}
    </div>
  );
}

export function RiskGauge({ value, review, alarm }: { value: number | null; review?: number; alarm?: number }) {
  const zone = value == null || review == null || alarm == null ? null : value >= alarm ? "alarm" : value >= review ? "review" : "low";
  const color = zone === "alarm" ? "var(--alarm)" : zone === "review" ? "var(--review)" : "var(--noalert)";
  const caption = zone === "alarm" ? "at or above the alarm threshold" : zone === "review" ? "between the review and the alarm threshold"
    : zone === "low" ? "below the review threshold" : "";
  const ticks = review != null && alarm != null ? [{ at: review, label: "review threshold" }, { at: alarm, label: "alarm threshold" }] : [];
  return <Gauge label="Risk" term="risk" value={value} color={color} ticks={ticks} caption={caption} />;
}

export function ConfidenceGauge({ value, gate }: { value: number | null; gate?: number }) {
  const below = value != null && gate != null && value < gate;
  const color = below ? "var(--review)" : "color-mix(in srgb, var(--foreground) 65%, transparent)";
  const caption = value == null ? "not computed (a processing step failed)" : below ? "below the gate: a person decides" : gate != null ? "above the gate" : "";
  return <Gauge label="Confidence" term="confidence" value={value} color={color} ticks={gate != null ? [{ at: gate, label: "confidence gate" }] : []} caption={caption} />;
}
