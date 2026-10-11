"use client";
// Demo mode step indicator: a small bar at the bottom while the presenter walks the jury path with → / ← (Esc ends it).
// It only navigates between real screens (lib/demo.ts); it never changes data.
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { DEMO_STEPS, demoStep, setDemoStep } from "@/lib/demo";
import { cn } from "@/lib/utils";

const subscribe = (cb: () => void) => { window.addEventListener("sentinel-demo", cb); window.addEventListener("storage", cb); return () => { window.removeEventListener("sentinel-demo", cb); window.removeEventListener("storage", cb); }; };
const typing = (el: EventTarget | null) => el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName));

export function DemoBar() {
  const router = useRouter();
  const step = useSyncExternalStore(subscribe, demoStep, () => null);
  const go = useCallback((i: number) => {
    const n = Math.max(0, Math.min(DEMO_STEPS.length - 1, i));
    setDemoStep(n);
    router.push(DEMO_STEPS[n].href);
  }, [router]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (step == null) { if (e.key === "D" && e.shiftKey) { e.preventDefault(); go(0); } return; }
      if (e.key === "ArrowRight") { e.preventDefault(); go(step + 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); go(step - 1); }
      else if (e.key === "Escape") setDemoStep(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, go]);

  if (step == null) return null;
  const s = DEMO_STEPS[step];
  return (
    <div role="region" aria-label="Demo path" className="fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
      {s.live && (
        <details className="elevated max-w-4xl rounded-2xl border border-border px-4 py-2 text-xs">
          <summary className="cursor-pointer text-muted-foreground">Optional: run it live in the terminal (~1 min per call)</summary>
          <div className="mt-2 flex items-start gap-2">
            <code className="block min-w-0 flex-1 break-all font-mono">{s.live}</code>
            <button type="button" onClick={() => void navigator.clipboard?.writeText(s.live!).catch(() => {})} className="shrink-0 rounded-full border border-border px-2 py-0.5 hover:bg-muted">copy</button>
          </div>
        </details>
      )}
      <div className="elevated flex max-w-4xl items-center gap-4 rounded-full border border-border px-4 py-2 text-sm">
        <button type="button" onClick={() => go(step - 1)} disabled={step === 0} aria-label="Previous step" className="rounded-full p-1 hover:bg-muted disabled:opacity-30"><ChevronLeft className="size-4" /></button>
        <ol className="flex items-center gap-1.5" aria-label={`Step ${step + 1} of ${DEMO_STEPS.length}`}>
          {DEMO_STEPS.map((d, i) => (
            <li key={i}><button type="button" onClick={() => go(i)} aria-label={`${d.moment}: ${d.title}`} aria-current={i === step ? "step" : undefined}
              className={cn("block h-2 rounded-full transition-all duration-[var(--dur-base)]", i === step ? "w-6 bg-foreground" : i < step ? "w-2 bg-foreground/60" : "w-2 bg-muted-foreground/40")} /></li>
          ))}
        </ol>
        <p className="min-w-0"><span className="font-semibold">{s.moment} · {s.title}</span><span className="hidden text-muted-foreground lg:inline"> — {s.say}</span></p>
        <span className="hidden whitespace-nowrap text-xs text-muted-foreground md:inline">← → · Esc</span>
        <button type="button" onClick={() => go(step + 1)} disabled={step === DEMO_STEPS.length - 1} aria-label="Next step" className="rounded-full p-1 hover:bg-muted disabled:opacity-30"><ChevronRight className="size-4" /></button>
        <button type="button" onClick={() => setDemoStep(null)} aria-label="End demo" className="rounded-full p-1 hover:bg-muted"><X className="size-4" /></button>
      </div>
    </div>
  );
}
