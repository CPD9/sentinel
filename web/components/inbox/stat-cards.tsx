"use client";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";
import type { Term } from "@/lib/glossary";
import { useEffect, useRef } from "react";
import { CRITERION_LABEL } from "@/lib/colors";
import type { CallListItem, Criterion } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The four big numbers at the top of the Overview, all counted from GET /api/calls. */
/** Plain names of the pipeline steps, for "now: …" in the Processing box. */
const STEP: Record<string, string> = {
  upload: "upload", asr: "transcription", diarize: "speaker separation", keywords: "keyword search", extract: "fact extraction",
  validate: "evidence check", rules: "checks", confidence: "confidence", decide: "decision", narrate: "writing the reason",
  snippets: "cutting snippets", analysis: "audio analysis", trigger: "notification",
};
export type Focus = "" | "alarm" | "review";

/** Four tinted boxes (after Proton Drive). Each number has one line of real information; Alarms and To review filter the list. */
export function StatCards({ calls, stages, focus, onFocus }: {
  calls: CallListItem[] | null; stages: Record<string, string>; focus: Focus; onFocus: (f: Focus) => void;
}) {
  if (!calls) {
    return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-busy="true">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[7.5rem] rounded-[20px]" />)}</div>;
  }
  const finished = calls.filter((c) => c.status === "done" || c.status === "error");
  const alarmCalls = finished.filter((c) => c.decision === "alarm");
  const reviewCalls = finished.filter((c) => c.decision === "review");
  const running = calls.filter((c) => c.status === "queued" || c.status === "processing");

  const byKind = new Map<string, number>();
  for (const c of alarmCalls) { const k = c.criteria[0] ?? "other"; byKind.set(k, (byKind.get(k) ?? 0) + 1); }
  const kinds = [...byKind.entries()].sort((x, y) => y[1] - x[1]);
  const alarmLine = kinds.length === 0 ? "none right now"
    : kinds.slice(0, 2).map(([k, n]) => `${n} ${(CRITERION_LABEL[k as Criterion] ?? k).toLowerCase()}`).join(", ") + (kinds.length > 2 ? ", …" : "");
  const failed = reviewCalls.filter((c) => c.n_stage_errors > 0).length;
  const reviewLine = reviewCalls.length === 0 ? "none right now" : failed === reviewCalls.length ? `${failed} after a failed step`
    : failed > 0 ? `${reviewCalls.length - failed} unsure, ${failed} after a failed step` : "the system was unsure";
  const flagged = alarmCalls.length + reviewCalls.length;
  const stage = running.map((c) => stages[c.call_id]).find(Boolean);

  const boxes: { key: string; label: string; value: number; line: string; term?: Term; tone?: string; focus?: Focus }[] = [
    { key: "alarm", label: "Alarms", value: alarmCalls.length, line: alarmLine, term: "alarm", tone: alarmCalls.length ? "text-alarm" : "", focus: "alarm" },
    { key: "review", label: "To review", value: reviewCalls.length, line: reviewLine, term: "review", tone: reviewCalls.length ? "text-review" : "", focus: "review" },
    { key: "checked", label: "Calls checked", value: finished.length, line: flagged ? `${flagged} needed a person` : "none needed a person" },
    { key: "running", label: "Processing", value: running.length, line: running.length === 0 ? "nothing in the queue" : stage ? `now: ${STEP[stage] ?? stage}` : "analysis running" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {boxes.map((b) => {
        const body = (
          <>
            <span className="flex items-center gap-1 text-sm font-medium text-muted-foreground">{b.label}{b.term && <InfoTip term={b.term} />}</span>
            <span className={cn("tabular mt-1 block text-4xl font-semibold tracking-tight", b.tone)}><CountUp value={b.value} /></span>
            <span className="mt-1 block truncate text-sm text-muted-foreground">{b.line}</span>
          </>
        );
        const cls = "surface-tint block rounded-[20px] px-5 py-4 text-left";
        if (!b.focus) return <div key={b.key} className={cls}>{body}</div>;
        const active = focus === b.focus;
        return (
          // a div with role=button (not <button>), so the ⓘ inside it stays a real, separately focusable button
          <div key={b.key} role="button" tabIndex={0} aria-pressed={active} title={active ? "Show all hits" : `Show only ${b.label.toLowerCase()}`}
            onClick={() => onFocus(active ? "" : b.focus!)}
            onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onFocus(active ? "" : b.focus!); } }}
            className={cn(cls, "cursor-pointer outline-offset-2 transition-shadow hover:ring-1 hover:ring-border", active && "ring-2 ring-primary hover:ring-2 hover:ring-primary")}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

/** Counts up from 0 once, on first load (the page's one load moment). Later updates and reduced motion show the value at once.
 *  Written to the DOM directly with a timer: no re-render per step, and no dependency on animation frames. */
function CountUp({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const played = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (played.current || value === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = String(value); played.current = true; return;
    }
    played.current = true;
    const t0 = performance.now(), D = 700;
    let finished = false;
    el.textContent = "0";
    const timer = setInterval(() => {
      const k = Math.min(1, (performance.now() - t0) / D);
      el.textContent = String(Math.round(value * (1 - Math.pow(1 - k, 3))));
      if (k >= 1) { finished = true; clearInterval(timer); }
    }, 16);
    return () => { clearInterval(timer); el.textContent = String(value); if (!finished) played.current = false; };
  }, [value]);
  return <span ref={ref} aria-label={String(value)} />;
}
