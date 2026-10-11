"use client";
// Segmented switch with a pill that slides to the active option (and takes that option's colour on the way).
// The pill is placed by writing to its style from a layout effect (no re-render), and follows size changes through a
// ResizeObserver, so a count that grows ("9" → "10") never leaves it misaligned. Arrow keys move between options.
import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Tween } from "@/components/ui/tween";
import { cn } from "@/lib/utils";

export interface SegmentedOption<K extends string> {
  key: K;
  label: string;
  icon?: ReactNode;
  count?: number;
  /** background of the pill while this option is active (CSS colour or var) */
  pill?: string;
  /** border colour of the pill while active */
  ring?: string;
  /** shown only from the sm breakpoint up; the icon stays */
  hideLabelOnPhone?: boolean;
}

export function Segmented<K extends string>({ options, value, onChange, label, size = "md" }: {
  options: SegmentedOption<K>[]; value: K; onChange: (k: K) => void; label: string; size?: "sm" | "md";
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  const btns = useRef(new Map<K, HTMLButtonElement>());
  const placed = useRef(false);
  const active = options.find((o) => o.key === value);

  useLayoutEffect(() => {
    const place = () => {
      const el = btns.current.get(value), p = pill.current;
      if (!el || !p) return;
      if (!placed.current) p.style.transition = "none";          // first placement: no slide in from the left edge
      p.style.width = `${el.offsetWidth}px`;
      p.style.transform = `translateX(${el.offsetLeft}px)`;
      p.style.background = active?.pill ?? "var(--card)";
      p.style.borderColor = active?.ring ?? "var(--border)";
      p.style.opacity = "1";
      if (!placed.current) { void p.offsetWidth; p.style.transition = ""; placed.current = true; }
    };
    place();
    const ro = new ResizeObserver(place);
    if (wrap.current) ro.observe(wrap.current);
    btns.current.forEach((b) => ro.observe(b));
    return () => ro.disconnect();
  }, [value, active]);

  const move = (dir: 1 | -1) => {
    const i = options.findIndex((o) => o.key === value);
    const next = options[(i + dir + options.length) % options.length];
    onChange(next.key);
    btns.current.get(next.key)?.focus();
  };

  return (
    <div ref={wrap} role="tablist" aria-label={label}
      onKeyDown={(e) => { if (e.key === "ArrowRight") { e.preventDefault(); move(1); } if (e.key === "ArrowLeft") { e.preventDefault(); move(-1); } }}
      className="relative inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-xl border border-border bg-muted/50 p-1">
      <span ref={pill} aria-hidden className="seg-pill pointer-events-none absolute inset-y-1 left-0 rounded-lg border opacity-0 shadow-sm" />
      {options.map((o) => {
        const on = o.key === value;
        return (
          <button key={o.key} ref={(el) => { if (el) btns.current.set(o.key, el); else btns.current.delete(o.key); }}
            type="button" role="tab" aria-selected={on} tabIndex={on ? 0 : -1} onClick={() => onChange(o.key)}
            className={cn("relative z-10 inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg font-medium transition-colors duration-200",
              size === "sm" ? "h-7 px-2.5 text-sm" : "h-9 px-3.5 text-sm",
              on ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {o.icon && <span className={cn("seg-icon inline-flex", on && "seg-icon-on")}>{o.icon}</span>}
            <span className={cn(o.hideLabelOnPhone && "sr-only sm:not-sr-only")}>{o.label}</span>
            {o.count != null && (
              <span className={cn("tabular min-w-6 rounded-full px-1.5 text-center text-xs font-semibold transition-colors duration-200",
                on ? "bg-foreground/10 text-foreground" : "bg-muted text-muted-foreground")}>
                <Tween value={o.count} />
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
