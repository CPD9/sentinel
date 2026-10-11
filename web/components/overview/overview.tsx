"use client";
// Overview (Nik's design 01): what SENTINEL does in three lines and today's result in one sentence, then one way in.
// Counts come from GET /calls; nothing is estimated.
import { ArrowRight, Check, Eye, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { Tween } from "@/components/ui/tween";
import { ErrorCard } from "@/components/shell/states";
import { Skeleton } from "@/components/ui/skeleton";
import { getCalls } from "@/lib/data";
import { setDemoStep } from "@/lib/demo";
import { useAsync } from "@/lib/use-async";

export function Overview() {
  const calls = useAsync(getCalls, "calls");
  const rows = calls.data ?? [];
  const n = (d: string) => rows.filter((c) => c.decision === d && c.status !== "queued" && c.status !== "processing").length;
  const counts = [
    { key: "alarm", label: "Alerts", hint: "a verified passage breaks a rule", icon: OctagonAlert, tone: "text-alarm", n: n("alarm") },
    { key: "review", label: "Reviews", hint: "the system is unsure, a person decides", icon: Eye, tone: "text-review", n: n("review") },
    { key: "no_alert", label: "No alerts", hint: "checked, nothing found", icon: Check, tone: "text-noalert", n: n("no_alert") },
  ];
  const errors = rows.filter((c) => c.n_stage_errors > 0).length;

  return (
    <div className="stage-in mx-auto max-w-6xl space-y-12 py-6">
      <section className="space-y-6">
        <p className="eyebrow">Sentinel · compliance check for Swiss German bank calls</p>
        {calls.status === "error" && !calls.data ? <ErrorCard error={calls.error} onRetry={calls.reload} title="Could not load today's calls" /> : !calls.data ? <Skeleton className="h-40 w-3/4" /> : (
          <h1 className="max-w-4xl text-[clamp(2.25rem,4.5vw,4rem)] font-semibold leading-[1.08] tracking-tight">
            You&rsquo;ve got <span className="text-alarm"><Tween value={counts[0].n} /> alert{counts[0].n === 1 ? "" : "s"}</span>,{" "}
            <span className="text-review"><Tween value={counts[1].n} /> review{counts[1].n === 1 ? "" : "s"}</span>,<br className="hidden md:block" />{" "}
            and <Tween value={counts[2].n} /> calls with no alert.
          </h1>
        )}
        <ul className="max-w-3xl space-y-1.5 text-lead text-muted-foreground">
          <li>Every call is transcribed and checked, not a sample.</li>
          <li>Each alert carries its reason, the passage it rests on and the facts behind it.</li>
          <li>When the system is unsure it says why and hands the call to a person.</li>
        </ul>
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Link href="/" className="inline-flex h-12 items-center gap-2 rounded-full bg-primary px-7 text-lead font-semibold text-primary-foreground hover:opacity-90">Open the alerts<ArrowRight className="size-5" /></Link>
          <Link href="/how-it-runs" className="inline-flex h-12 items-center rounded-full border border-foreground/60 px-7 text-lead font-semibold hover:bg-muted">How it runs</Link>
          <button type="button" onClick={() => setDemoStep(0)} className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline" title="Guided path over the real screens: → / ←, Esc to end (or Shift+D anywhere)">Start the demo path</button>
        </div>
      </section>

      <section aria-label="Today" className="grid gap-5 md:grid-cols-3">
        {counts.map((c, i) => (
          <Link key={c.key} href="/" className="elevated stage-in group rounded-[var(--radius-panel)] p-6 transition-colors hover:bg-muted" style={{ "--i": i + 1 } as React.CSSProperties}>
            <c.icon className={`size-8 ${c.tone}`} aria-hidden />
            <p className="tabular mt-4 text-display font-semibold">{calls.data ? <Tween value={c.n} /> : "–"}</p>
            <p className="text-lead font-semibold">{c.label}</p>
            <p className="text-sm text-muted-foreground">{c.hint}</p>
          </Link>
        ))}
      </section>
      {calls.data && (
        <p className="text-sm text-muted-foreground">
          {rows.length} calls checked{errors ? ` · ${errors} with a failed step, shown on the call` : ""}. Self-hosted: no call leaves our own servers, and no cloud AI service is used.
        </p>
      )}
    </div>
  );
}
