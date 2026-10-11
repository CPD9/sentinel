"use client";
// Left panel of the Overview: every call, grouped by what the officer has to do with it.
//   Alarms → To review → No alert (folded, it is the bulk) → Processing (only when something is running).
// Each row is a link to /?call=<id>, so the selection lives in the URL (back button, reload and sharing work).
import { Check, ChevronRight, Eye, Loader2, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { StageErrorChip } from "@/components/shell/badges";
import { Skeleton } from "@/components/ui/skeleton";
import { CRITERION_LABEL } from "@/lib/colors";
import type { CallListItem, Criterion } from "@/lib/types";
import { cn } from "@/lib/utils";

export type Group = "alarm" | "review" | "no_alert" | "processing";

const GROUPS: { key: Group; title: string; icon: typeof Check; color: string; empty: string }[] = [
  { key: "alarm", title: "Alarms", icon: OctagonAlert, color: "text-alarm", empty: "No alarm right now." },
  { key: "review", title: "To review", icon: Eye, color: "text-review", empty: "Nothing waits for a person." },
  { key: "no_alert", title: "No alert", icon: Check, color: "text-noalert", empty: "No call has been cleared yet." },
  { key: "processing", title: "Processing", icon: Loader2, color: "text-info", empty: "" },
];

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
    : rows.sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0));
}

/** "10 Oct, 14:02" in UTC, the same clock as the rest of the app. */
const shortTime = (iso: string | null) => {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d.getTime())
    ? d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })
    : "–";
};

export function CallList({ calls, selected, stages }: { calls: CallListItem[] | null; selected: string | null; stages: Record<string, string> }) {
  // No alert starts folded. When a call gets selected (also via a shared link), its group opens once; after that the
  // officer can still fold it. (Adjusting state while rendering, the React pattern for "react to a prop change".)
  const [open, setOpen] = useState<Record<Group, boolean>>({ alarm: true, review: true, no_alert: false, processing: true });
  const [revealed, setRevealed] = useState<string | null>(null);
  const selectedRow = calls?.find((c) => c.call_id === selected);
  if (selectedRow && revealed !== selectedRow.call_id) {
    setRevealed(selectedRow.call_id);
    const g = groupOf(selectedRow);
    if (!open[g]) setOpen({ ...open, [g]: true });
  }
  const isOpen = (g: Group) => open[g];

  if (!calls) {
    return (
      <div className="space-y-2" aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
      </div>
    );
  }

  return (
    <nav aria-label="Calls" className="space-y-5">
      {GROUPS.map(({ key, title, icon: Icon, color, empty }) => {
        const rows = callsIn(calls, key);
        if (key === "processing" && rows.length === 0) return null;
        const expanded = isOpen(key);
        return (
          <section key={key} aria-labelledby={`grp-${key}`}>
            <h2 id={`grp-${key}`}>
              <button type="button" aria-expanded={expanded} onClick={() => setOpen((o) => ({ ...o, [key]: !expanded }))}
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left hover:bg-muted">
                <Icon className={cn("size-6 shrink-0", color, key === "processing" && "animate-spin motion-reduce:animate-none")} aria-hidden />
                <span className="text-2xl font-semibold tracking-tight">{title}</span>
                <ChevronRight className={cn("size-4 text-muted-foreground transition-transform motion-reduce:transition-none", expanded && "rotate-90")} aria-hidden />
                <span className="tabular ml-auto text-2xl font-semibold" aria-label={`${rows.length} calls`}>{rows.length}</span>
              </button>
            </h2>
            {expanded && (rows.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground">{empty}</p>
            ) : (
              <ul className="mt-1 divide-y divide-border/60">
                {rows.map((c) => <Row key={c.call_id} c={c} active={c.call_id === selected} stage={stages[c.call_id]} />)}
              </ul>
            ))}
          </section>
        );
      })}
    </nav>
  );
}

function Row({ c, active, stage }: { c: CallListItem; active: boolean; stage?: string }) {
  const g = groupOf(c);
  const criterion = c.criteria[0] as Criterion | undefined;
  const sub = g === "processing" ? (c.status === "queued" ? "queued" : `processing${stage ? ` · ${stage}` : ""}`)
    : criterion ? CRITERION_LABEL[criterion] ?? criterion : g === "no_alert" ? "nothing found" : "";
  // risk 0 on a call with a stage error means "never checked", not "safe": show nothing rather than 0%
  const unchecked = c.n_stage_errors > 0 && !c.risk_score;
  const risk = c.risk_score == null || g === "processing" || unchecked ? null : `${Math.round(c.risk_score * 100)}%`;
  const riskColor = g === "alarm" ? "text-alarm" : g === "review" ? "text-review" : "text-muted-foreground";

  return (
    <li>
      <Link href={`/?call=${encodeURIComponent(c.call_id)}`} replace scroll={false} aria-current={active ? "true" : undefined}
        className={cn("relative grid grid-cols-[minmax(0,1fr)_3.5rem_6.5rem] items-center gap-4 rounded-lg px-3 py-2.5 transition-colors",
          active ? "bg-primary/12 before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-primary" : "hover:bg-muted")}>
        <div className="min-w-0">
          <p className={cn("truncate font-mono text-sm", active && "font-semibold")}>{c.call_id}</p>
          <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
            {sub}<StageErrorChip count={c.n_stage_errors} />
          </p>
        </div>
        <p className={cn("tabular text-right text-sm font-semibold", riskColor)}>{risk ?? ""}</p>
        <p className="tabular text-right text-sm text-muted-foreground">{shortTime(c.updated_at)}</p>
      </Link>
    </li>
  );
}
