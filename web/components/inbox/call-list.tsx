"use client";
// Left panel of the Overview: the calls of one group, picked with the tabs above (Alerts → To review → No alert →
// Processing, the last only while something runs). Each row is a link to /?call=<id>, so the selection lives in the URL
// (back button, reload and sharing work).
import { Check, Eye, Loader2, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { StageErrorChip } from "@/components/shell/badges";
import { Skeleton } from "@/components/ui/skeleton";
import { CRITERION_LABEL } from "@/lib/colors";
import type { CallListItem, Criterion } from "@/lib/types";
import { cn } from "@/lib/utils";

export type Group = "alarm" | "review" | "no_alert" | "processing";

export const GROUPS: { key: Group; title: string; icon: typeof Check; color: string; empty: string }[] = [
  { key: "alarm", title: "Alerts", icon: OctagonAlert, color: "text-alarm", empty: "No alerts right now." },
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

/** Rows of one group (the tab above the list). `dir` is the direction of the last tab change: rows slide in from that side. */
export function CallList({ calls, group, selected, stages, dir }: {
  calls: CallListItem[] | null; group: Group; selected: string | null; stages: Record<string, string>; dir: 1 | -1;
}) {
  if (!calls) {
    return (
      <div className="space-y-2 p-1" aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
      </div>
    );
  }
  const meta = GROUPS.find((g) => g.key === group)!;
  const rows = callsIn(calls, group);
  if (rows.length === 0) {
    return (
      <div key={group} className="row-in flex h-full min-h-48 flex-col items-center justify-center gap-2 text-center" style={{ "--dir": dir } as React.CSSProperties}>
        <meta.icon className={cn("size-6", meta.color)} aria-hidden />
        <p className="text-sm text-muted-foreground">{meta.empty}</p>
      </div>
    );
  }
  // keyed by the group: a tab change re-mounts the list, so the rows play their entrance again
  return (
    <ul key={group} aria-label={meta.title} className="space-y-0.5">
      {rows.map((c, i) => (
        <Row key={c.call_id} c={c} active={c.call_id === selected} stage={stages[c.call_id]}
          style={{ "--dir": dir, animationDelay: `${Math.min(i, 12) * 28}ms` } as React.CSSProperties} />
      ))}
    </ul>
  );
}

function Row({ c, active, stage, style }: { c: CallListItem; active: boolean; stage?: string; style?: React.CSSProperties }) {
  const g = groupOf(c);
  const criterion = c.criteria[0] as Criterion | undefined;
  const sub = g === "processing" ? (c.status === "queued" ? "queued" : `processing${stage ? ` · ${stage}` : ""}`)
    : criterion ? CRITERION_LABEL[criterion] ?? criterion : g === "no_alert" ? "nothing found" : "";
  // risk 0 on a call with a stage error means "never checked", not "safe": show nothing rather than 0%
  const unchecked = c.n_stage_errors > 0 && !c.risk_score;
  const risk = c.risk_score == null || g === "processing" || unchecked ? null : `${Math.round(c.risk_score * 100)}%`;
  const riskColor = g === "alarm" ? "text-alarm" : g === "review" ? "text-review" : "text-muted-foreground";
  // keep the open call in view inside the scrolling list (also when moving with the arrow keys). Wide screens only:
  // on a phone the list does not scroll on its own, and the page glides down to the panel instead.
  const ref = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    if (active && window.matchMedia("(min-width: 1024px)").matches) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);

  return (
    <li className="row-in" style={style}>
      <Link ref={ref} href={`/?call=${encodeURIComponent(c.call_id)}`} replace scroll={false} aria-current={active ? "true" : undefined}
        className={cn("group/row relative grid grid-cols-[minmax(0,1fr)_3.5rem_6.5rem] items-center gap-4 rounded-lg px-3 py-2.5 transition-[background-color,transform] duration-200 active:scale-[0.99] motion-reduce:transition-none",
          active ? "bg-primary/12" : "hover:bg-muted hover:translate-x-0.5")}>
        <span aria-hidden className={cn("row-bar absolute inset-y-2 left-0 w-[3px] rounded-full bg-primary", active ? "row-bar-on" : "")} />
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
