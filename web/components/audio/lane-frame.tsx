"use client";
import { useEffect, useState } from "react";
import { fmtTime } from "@/lib/format";
import type { Axes } from "@/lib/types";

export const LABEL_W = 168;
export const RIGHT_W = 76;

export interface Scale { t0: number; t1: number; w: number }
export const xOf = (s: Scale, t: number) => ((t - s.t0) / (s.t1 - s.t0)) * s.w;
export const tOf = (s: Scale, px: number) => s.t0 + (px / s.w) * (s.t1 - s.t0);
export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function useWidth<T extends HTMLElement>() {
  // Callback ref: re-observes when the measured element is swapped (skeleton → real content).
  const [el, setEl] = useState<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w] as const;
}

/** "Nice" tick step in seconds so that about one label fits every 90 px. */
export function timeTicks(s: Scale): number[] {
  const span = s.t1 - s.t0;
  const target = Math.max(2, s.w / 90);
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find((x) => span / x <= target) ?? 600;
  const out: number[] = [];
  for (let t = Math.ceil(s.t0 / step) * step; t <= s.t1 + 1e-9; t += step) out.push(+t.toFixed(3));
  return out;
}

export function fmtTick(t: number, step?: number) { return fmtTime(t, step != null && step < 1); }

/** Row of the lane stack: label gutter | plot | right gutter. Label, units and tick labels come from the data's `axes`. */
export function Lane({
  title, axes, axis = "y", height, ticks, badge, note, right, children, scale, raw,
}: {
  raw?: boolean;
  title: string; axes?: Axes; axis?: "y" | "value"; height: number; scale: Scale;
  ticks?: { y: number; label: string }[]; badge?: React.ReactNode; note?: string; right?: React.ReactNode; children: React.ReactNode;
}) {
  const a = axes?.[axis];
  return (
    <div className="flex" style={{ height }}>
      <div className="flex shrink-0 flex-col justify-between pr-10 text-right" style={{ width: LABEL_W }}>
        <div>
          <div className="text-xs font-semibold leading-tight">{title}</div>
          {a && <div className="text-[10px] leading-tight text-muted-foreground">{a.label} ({a.unit})</div>}
          {note && <div className="mt-0.5 text-[10px] leading-tight text-review">{note}</div>}
          {badge && <div className="mt-1 flex justify-end">{badge}</div>}
        </div>
      </div>
      <div className="relative" style={{ width: scale.w, height }}>
        {ticks?.map((t) => (
          <span key={t.label + t.y} className="tabular absolute -left-1 -translate-x-full text-[10px] leading-none text-muted-foreground" style={{ top: clamp(t.y - 5, 0, height - 10) }}>{t.label}</span>
        ))}
        {raw ? children : (
          <svg width={scale.w} height={height} className="block rounded-sm border border-border" style={{ background: "var(--lane-bg)" }} aria-hidden>
            <TimeGrid scale={scale} height={height} />
            {children}
          </svg>
        )}
      </div>
      <div className="shrink-0 pl-2" style={{ width: RIGHT_W }}>{right}</div>
    </div>
  );
}

export function TimeGrid({ scale, height }: { scale: Scale; height: number }) {
  return <g stroke="var(--grid)" strokeWidth={1}>{timeTicks(scale).map((t) => <line key={t} x1={xOf(scale, t)} x2={xOf(scale, t)} y1={0} y2={height} />)}</g>;
}

export function TimeAxis({ scale, axes }: { scale: Scale; axes?: Axes }) {
  const x = axes?.x;
  return (
    <div className="flex" style={{ height: 38 }}>
      <div style={{ width: LABEL_W }} />
      <div className="relative" style={{ width: scale.w }}>
        {timeTicks(scale).map((t) => (
          <div key={t} className="absolute top-0 -translate-x-1/2 text-center" style={{ left: xOf(scale, t) }}>
            <div className="mx-auto h-1.5 w-px bg-[var(--axis)]" />
            <span className="tabular text-[10px] text-muted-foreground">{fmtTime(t)}</span>
          </div>
        ))}
        <div className="absolute bottom-0 w-full text-center text-[11px] font-medium text-muted-foreground">{x ? `${x.label} (${x.unit}) — tick labels mm:ss` : "time"}</div>
      </div>
    </div>
  );
}
