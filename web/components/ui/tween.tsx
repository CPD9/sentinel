"use client";
// A number that glides to its new value (≈250 ms) instead of jumping: "1 → 0" while dragging a slider.
// Written to the DOM with a timer: no re-render per step, no dependency on animation frames, none with reduced motion.
import { useEffect, useRef } from "react";

export function Tween({ value, format = (n) => String(Math.round(n)), className }: { value: number; format?: (n: number) => string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const from = shown.current;
    if (from == null || from === value || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = format(value); shown.current = value; return;
    }
    const t0 = performance.now(), D = 250;
    const timer = setInterval(() => {
      const k = Math.min(1, (performance.now() - t0) / D);
      const v = from + (value - from) * (1 - Math.pow(1 - k, 3));
      el.textContent = format(v); shown.current = v;
      if (k >= 1) { clearInterval(timer); shown.current = value; }
    }, 16);
    return () => { clearInterval(timer); el.textContent = format(value); shown.current = value; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return <span ref={ref} className={className} />;
}
