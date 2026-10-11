"use client";
// Left panel of the inbox (Nik's design 04): every call, grouped by what the officer has to do with it.
//   Alert → Review → No alert (folded, it is the bulk) → Processing (only when something is running).
// One plain line per row: an Alert says what was found, a Review says why the system is unsure (never a risk number that
// looks like an alert), a No alert says whether keywords were heard. Lines come from the decision trace.
// Each row links to /?call=<id>, so the selection lives in the URL; j / k move it, Enter opens the call (inbox-view.tsx).
import { Check, ChevronRight, Eye, Loader2, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { StageErrorChip } from "@/components/shell/badges";
import { Skeleton } from "@/components/ui/skeleton";
import { CRITERION_LABEL } from "@/lib/colors";
import { plainReason, score, unsureFromPath, unsureLine } from "@/lib/explain";
import type { CallListItem, Criterion, DecisionTrace } from "@/lib/types";
import { cn } from "@/lib/utils";

export type Group = "alarm" | "review" | "no_alert" | "processing";

const GROUPS: { key: Group; title: string; icon: typeof Check; color: string; empty: string }[] = [
  { key: "alarm", title: "Alert", icon: OctagonAlert, color: "text-alarm", empty: "No alert right now." },
  { key: "review", title: "Review", icon: Eye, color: "text-review", empty: "Nothing waits for a person." },
  { key: "no_alert", title: "No alert", icon: Check, color: "text-noalert", empty: "No call has been cleared yet." },
  { key: "processing", title: "Processing", icon: Loader2, color: "text-info", empty: "" },
];
export const GROUP_ORDER: Group[] = GROUPS.map((g) => g.key);

/** Which group a call belongs to. Queued and processing calls have no decision yet. */
export function groupOf(c: CallListItem): Group {
  if (c.status === "queued" || c.status === "processing" || !c.decision) return "processing";
  return c.decision;
}

/** Calls of one group, highest risk first (processing: newest first). */
export function callsIn(calls: CallListItem[], g: Group): CallListItem[] {
  const rows = calls.filter((c) => groupOf(c) === g);
  return g === "processing"
    ? rows.sort((a, b) => (Date.parse(b.updated_at ?? "") || 0) - (Date.parse(a.updated_at ?? "") || 0))
    : rows.sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0) || a.call_id.localeCompare(b.call_id));
}

/** "10.10.26" in UTC, the same clock as the rest of the app. */
const shortDate = (iso: string | null) => {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d.getTime()) ? d.toLocaleDateString("de-CH", { day: "2-digit", month: "2-digit", year: "2-digit", timeZone: "UTC" }) : "–";
};

export function CallList({ calls, selected, stages, traces, open, setOpen }: {
  calls: CallListItem[] | null; selected: string | null; stages: Record<string, string>; traces: Map<string, DecisionTrace>;
  open: Record<Group, boolean>; setOpen: (g: Group, v: boolean) => void;
}) {
  if (!calls) {
    return (
      <div className="space-y-2" aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
      </div>
    );
  }

  return (
    <nav aria-label="Calls" className="space-y-6">
      {GROUPS.map(({ key, title, icon: Icon, color, empty }) => {
        const rows = callsIn(calls, key);
        if (key === "processing" && rows.length === 0) return null;
        const expanded = open[key];
        return (
          <section key={key} aria-labelledby={`grp-${key}`}>
            <h2 id={`grp-${key}`}>
              <button type="button" aria-expanded={expanded} onClick={() => setOpen(key, !expanded)}
                className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-muted">
                <Icon className={cn("size-8 shrink-0", color, key === "processing" && "animate-spin motion-reduce:animate-none")} aria-hidden />
                <span className="text-headline font-semibold tracking-tight">{title}</span>
                <ChevronRight className={cn("size-4 text-muted-foreground transition-transform duration-[var(--dur-fast)] motion-reduce:transition-none", expanded && "rotate-90")} aria-hidden />
                <span className="tabular ml-auto text-headline font-semibold" aria-label={`${rows.length} calls`}>{rows.length}</span>
              </button>
            </h2>
            {expanded && (rows.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground">{empty}</p>
            ) : (
              <ul className="mt-1 divide-y divide-border">
                {rows.map((c) => <Row key={c.call_id} c={c} active={c.call_id === selected} stage={stages[c.call_id]} trace={traces.get(c.call_id) ?? null} />)}
              </ul>
            ))}
          </section>
        );
      })}
    </nav>
  );
}

function Row({ c, active, stage, trace }: { c: CallListItem; active: boolean; stage?: string; trace: DecisionTrace | null }) {
  const g = groupOf(c);
  const ref = useRef<HTMLAnchorElement>(null);
  useEffect(() => { if (active) ref.current?.scrollIntoView({ block: "nearest" }); }, [active]);

  const criterion = c.criteria[0] as Criterion | undefined;
  const line = g === "processing" ? (c.status === "queued" ? "queued" : `processing${stage ? ` · ${stage}` : ""}`)
    : c.n_stage_errors > 0 ? "A processing step failed"
    : g === "alarm" ? (trace ? plainReason(trace) : null) ?? (criterion ? CRITERION_LABEL[criterion] : "")
    : g === "review" ? (trace ? unsureLine(trace) : unsureFromPath(c.decision_path) ?? "Unsure: details inside")
    : trace && trace.keyword_hits.length > 0 ? "Keywords heard, no rule broken" : "Nothing found";
  // risk 0 on a call with a stage error means "never checked", not "safe": show nothing rather than 0.
  const showRisk = g === "alarm" && c.risk_score != null && !(c.n_stage_errors > 0 && !c.risk_score);

  return (
    <li>
      <Link ref={ref} href={`/?call=${encodeURIComponent(c.call_id)}`} replace scroll={false} aria-current={active ? "true" : undefined}
        className={cn("grid grid-cols-[minmax(0,1fr)_4.5rem_4.5rem] items-center gap-3 rounded-lg px-3 py-2.5 transition-colors duration-[var(--dur-fast)]",
          active ? "bg-primary text-primary-foreground" : "hover:bg-muted")}>
        <div className="min-w-0">
          <p className={cn("truncate font-mono text-[15px]", active && "font-semibold")}>{c.call_id}</p>
          <p className={cn("flex items-center gap-1.5 truncate text-xs", active ? "opacity-80" : g === "review" ? "text-review" : "text-muted-foreground")}>
            <span className="truncate">{line}</span><StageErrorChip count={c.n_stage_errors} />
          </p>
        </div>
        <p className={cn("tabular text-right text-sm", !active && g === "alarm" && "font-semibold text-alarm")}>
          {showRisk ? <><span className={cn("text-xs font-normal", active ? "opacity-80" : "text-muted-foreground")}>Risk </span>{score(c.risk_score)}</> : ""}
        </p>
        <p className={cn("tabular text-right text-sm", active ? "opacity-80" : "text-muted-foreground")}>{shortDate(c.updated_at)}</p>
      </Link>
    </li>
  );
}
