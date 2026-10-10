"use client";
// The alarm-threshold slider with every decided call as a pin hanging from the track at its risk, like the marks of a
// ruler. A pin takes the colour of the decision the call would get with the current draft (from the simulation's flipped
// list) and gets a violet outline when that decision would change. Calls at (almost) the same risk stack into a taller pin,
// one coloured segment per call, so the lane reads like a tiny bar chart. The track uses the same grey → amber → red
// gradient as the Overview gauges, with the stops on the draft thresholds.
import { pct } from "@/lib/format";
import type { CallListItem, Decision } from "@/lib/types";

const GREY = "color-mix(in srgb, var(--noalert) 55%, var(--card))";
const SOFT = 3;
const COLOUR: Record<Decision, string> = { alarm: "var(--gauge-alarm)", review: "var(--gauge-review)", no_alert: "var(--noalert)" };
const LABEL: Record<Decision, string> = { alarm: "alarm", review: "review", no_alert: "no alert" };
/** Position on the track: the thumb is 18 px wide, so 0 % sits 9 px from the left edge and 100 % 9 px from the right. */
const at = (x: number) => `calc(9px + ${Math.min(1, Math.max(0, x))} * (100% - 18px))`;
const clampPct = (x: number) => Math.min(100, Math.max(0, x));
// geometry: the input is 24 px tall with the 6 px track centred, so the track's lower edge is 15 px from the top
const TRACK_BOTTOM = 15, SEG = 10, GAP = 1;

export function ThresholdTrack({ id, value, saved, review, calls, after, onChange }: {
  id: string; value: number; saved: number; review: number; calls: CallListItem[];
  after: Map<string, Decision>;   // call id → decision with the draft (only calls that would change)
  onChange: (v: number) => void;
}) {
  const r = review * 100, a = value * 100;
  const gradient = `linear-gradient(to right, ${GREY} 0% ${clampPct(r - SOFT)}%, var(--gauge-review) ${clampPct(r + SOFT)}% ${clampPct(a - SOFT)}%, var(--gauge-alarm) ${clampPct(a + SOFT)}% 100%)`;

  // one pin per 2 % of risk; each call is one segment of it
  const pins = new Map<number, { risk: number; segs: { c: CallListItem; d: Decision; changed: boolean }[] }>();
  for (const c of calls) {
    if (c.risk_score == null || !c.decision) continue;
    const bucket = Math.round(c.risk_score * 50);
    const pin = pins.get(bucket) ?? { risk: bucket / 50, segs: [] };
    pin.segs.push({ c, d: after.get(c.call_id) ?? c.decision, changed: after.has(c.call_id) });
    pins.set(bucket, pin);
  }
  const tallest = Math.max(1, ...[...pins.values()].map((p) => p.segs.length));
  const laneH = 4 + tallest * (SEG + GAP);

  return (
    <div>
      <div className="relative" style={{ marginBottom: Math.max(0, TRACK_BOTTOM + laneH - 24) }}>
        <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full" style={{ left: 9, right: 9, background: gradient }} aria-hidden />
        {/* the calls, hanging from the track */}
        {[...pins.values()].map((p) => (
          <div key={p.risk} className="absolute flex -translate-x-1/2 flex-col items-center" style={{ left: at(p.risk), top: TRACK_BOTTOM + 1, gap: GAP }}
            title={p.segs.map((s) => `${s.c.call_id}: risk ${pct(s.c.risk_score)}, ${s.changed ? `would become ${LABEL[s.d]}` : LABEL[s.d]}`).join("\n")}>
            {p.segs.map((s) => (
              <span key={s.c.call_id} className="call-dot block w-1.5 rounded-sm"
                style={{ height: SEG, background: COLOUR[s.d], boxShadow: s.changed ? "0 0 0 1.5px var(--primary)" : undefined }} />
            ))}
          </div>
        ))}
        <span aria-hidden title={`saved ${pct(saved)}`} className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground/50" style={{ left: at(saved) }} />
        <input id={id} type="range" min={0} max={1} step={0.01} value={value} onChange={(e) => onChange(+e.target.value)}
          className="sens-range" aria-valuetext={`${pct(value)} alarm threshold`} />
      </div>
      <div className="mt-1 flex justify-between gap-4 text-xs text-muted-foreground">
        <span>catches more</span>
        <span className="text-right">fewer false alarms</span>
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>Calls on the scale:</span>
        {(["alarm", "review", "no_alert"] as Decision[]).map((d) => (
          <span key={d} className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-1.5 rounded-sm" style={{ background: COLOUR[d] }} />{LABEL[d]}</span>
        ))}
        <span className="flex items-center gap-1"><span aria-hidden className="inline-block h-2.5 w-1.5 rounded-sm bg-muted-foreground/40" style={{ boxShadow: "0 0 0 1.5px var(--primary)" }} />would change</span>
      </p>
    </div>
  );
}
