"use client";
// ⓘ button with a short explanation from the glossary.
// Built against the usual failures of hover tips: it renders in a portal with fixed positioning (never clipped by a card),
// flips above when there is no room below and stays inside the screen, follows scroll and resize, has hover intent
// (moving from the icon onto the bubble keeps it open), works on touch (tap toggles, tap outside closes) and with the
// keyboard (focus opens, Escape closes), and never triggers the card or link it sits in.
import { Info } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { GLOSSARY, type Term } from "@/lib/glossary";
import { cn } from "@/lib/utils";

type Phase = "closed" | "enter" | "open" | "exit";
const OPEN_DELAY = 90, CLOSE_DELAY = 160, EXIT_MS = 110, GAP = 8, MARGIN = 8;

export function InfoTip({ term, className }: { term: Term; className?: string }) {
  const { title, text } = GLOSSARY[term];
  const id = useId();
  const btn = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [phase, setPhase] = useState<Phase>("closed");
  const [pinned, setPinned] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; origin: string; above: boolean } | null>(null);
  const shown = phase !== "closed";

  const clear = () => { if (timer.current) { clearTimeout(timer.current); timer.current = null; } };
  const open = useCallback(() => { clear(); setPhase((p) => (p === "open" || p === "enter" ? p : "enter")); }, []);
  const close = useCallback(() => {
    clear();
    setPinned(false);
    setPhase((p) => (p === "closed" ? p : "exit"));
    timer.current = setTimeout(() => setPhase("closed"), EXIT_MS);
  }, []);
  const later = (fn: () => void, ms: number) => { clear(); timer.current = setTimeout(fn, ms); };

  // enter → open a moment later, so the CSS transition has a start state. A timer, not requestAnimationFrame:
  // some browsers pause animation frames in embedded or background views, which would leave the bubble invisible.
  useEffect(() => {
    if (phase !== "enter") return;
    const t = setTimeout(() => setPhase("open"), 16);
    return () => clearTimeout(t);
  }, [phase]);
  useEffect(() => () => clear(), []);

  // position: below the icon, or above when there is no room; clamped to the screen
  const place = useCallback(() => {
    const b = btn.current?.getBoundingClientRect(), t = tip.current;
    if (!b || !t) return;
    const w = t.offsetWidth, h = t.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    const above = b.bottom + GAP + h > vh - MARGIN && b.top - GAP - h > MARGIN;
    const left = Math.min(Math.max(b.left + b.width / 2 - w / 2, MARGIN), vw - w - MARGIN);
    const top = above ? b.top - GAP - h : b.bottom + GAP;
    setPos({ top, left, above, origin: `${b.left + b.width / 2 - left}px ${above ? "100%" : "0"}` });
  }, []);
  useLayoutEffect(() => { if (shown) place(); }, [shown, place]);
  useEffect(() => {
    if (!shown) return;
    const onMove = () => place();   // scroll/resize events already arrive at most once per frame
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { close(); btn.current?.focus(); } };
    const onDown = (e: PointerEvent) => {
      const n = e.target as Node;
      if (!btn.current?.contains(n) && !tip.current?.contains(n)) close();
    };
    window.addEventListener("scroll", onMove, { passive: true, capture: true });
    window.addEventListener("resize", onMove);
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("scroll", onMove, { capture: true });
      window.removeEventListener("resize", onMove);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [shown, place, close]);

  const hoverIn = (e: React.PointerEvent) => { if (e.pointerType === "mouse" && !pinned) later(open, OPEN_DELAY); };
  const hoverOut = (e: React.PointerEvent) => { if (e.pointerType === "mouse" && !pinned) later(close, CLOSE_DELAY); };

  return (
    <>
      <button ref={btn} type="button" aria-label={`What is “${title}”?`} aria-expanded={shown} aria-describedby={shown ? id : undefined}
        className={cn("inline-flex size-5 shrink-0 items-center justify-center rounded-full align-middle text-muted-foreground transition-colors hover:text-link focus-visible:text-link", shown && "text-link", className)}
        onPointerEnter={hoverIn} onPointerLeave={hoverOut}
        onFocus={(e) => { if (e.currentTarget.matches(":focus-visible")) open(); }}
        onBlur={() => { if (!pinned) later(close, CLOSE_DELAY); }}
        onClick={(e) => {
          e.preventDefault(); e.stopPropagation();          // never trigger the card or link around it
          if (pinned) close(); else { setPinned(true); open(); }
        }}>
        <Info className="size-3.5" aria-hidden />
      </button>
      {shown && createPortal(
        <div ref={tip} id={id} role="tooltip" data-state={phase === "open" ? "open" : phase === "exit" ? "exit" : "enter"}
          onPointerEnter={(e) => { if (e.pointerType === "mouse") clear(); }} onPointerLeave={hoverOut}
          className="info-tip fixed z-[60] w-[min(20rem,calc(100vw-16px))] rounded-xl border border-border bg-card px-3.5 py-3 text-left shadow-lg shadow-black/30"
          style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999, transformOrigin: pos?.origin }}>
          <p className="text-sm font-semibold">{title}</p>
          <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{text}</p>
        </div>,
        document.body,
      )}
    </>
  );
}
