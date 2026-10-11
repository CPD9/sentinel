"use client";
// Sensitivity: one focal panel (the alarm threshold, every call as a dot on it, and what changes if you save), then the
// context card with tabs (test-set trade-off, suggestions from feedback, change log).
// The unsaved draft is shared with the suggestions' Preview via SettingsDraftProvider; nothing is saved until "Save changes".
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Eye, History, Lightbulb, LineChart, OctagonAlert, Save, UserRound } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { DecisionBadge } from "@/components/shell/badges";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { InfoTip } from "@/components/ui/info-tip";
import { Segmented } from "@/components/ui/segmented";
import { Tween } from "@/components/ui/tween";
import { ApiError, getCalls, getQualityReport, getQualityReports, getThresholds, isFixtures, saveDraft } from "@/lib/data";
import { componentLabel, pct } from "@/lib/format";
import type { Term } from "@/lib/glossary";
import { useSettingsDraft } from "@/lib/settings-draft";
import type { CallListItem, Decision, Patch, Thresholds } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { useSimulate } from "@/lib/use-simulate";
import { cn } from "@/lib/utils";
import { AuditLog } from "./audit-log";
import { CurveChart } from "./curve-chart";
import { SuggestionsCard } from "./suggestions-card";
import { ThresholdTrack } from "./threshold-track";

const errText = (e: unknown) => (e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : `${e.code}: ${e.detail}`) : String(e));
const DECIDED = (c: CallListItem) => (c.status === "done" || c.status === "error") && c.decision != null;

export function Tuning() {
  const saved = useAsync(getThresholds, "thresholds");
  const calls = useAsync(getCalls, "calls");
  const report = useAsync(async () => { const r = await getQualityReports(); return r.length ? getQualityReport(r[0].report_id) : null; }, "tuning-report");
  const { draft: d, setThreshold, loadPatch, reset, toPatch } = useSettingsDraft();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [applied, setApplied] = useState<string | null>(null);   // lives here, not in the keyed card, so a remount cannot clear it
  const [epoch, setEpoch] = useState(0);              // bumps after a save/apply so suggestions and the change log reload
  const [more, setMore] = useState<"tradeoff" | "suggestions" | "log">("tradeoff");   // the context card's tab

  const draft = d.thresholds ?? saved.data;
  const patch = toPatch(saved.data);
  const sim = useSimulate(patch);
  const result = sim.data ?? sim.stale;
  const after = useMemo(() => new Map<string, Decision>(patch && result ? result.flipped.map((f) => [f.call_id, f.after]) : []), [patch, result]);

  if (saved.status === "error" && !saved.data) return <ErrorCard error={saved.error} onRetry={saved.reload} />;
  if (!draft || !saved.data) return <SkeletonBlock rows={6} />;

  const set = (k: keyof Thresholds, v: number) => { setMsg(null); setApplied(null); setThreshold(saved.data!, k, v); };
  const save = async () => {
    if (!patch) return;
    try {
      const r = await saveDraft(patch);
      setMsg({ ok: true, text: `Saved. The decisions of ${r.rerun.n_calls} calls are being re-made from the cached transcripts; nothing is re-transcribed.` });
      reset(); saved.reload(); calls.reload(); setEpoch((e) => e + 1);
    } catch (e) { setMsg({ ok: false, text: errText(e) }); }
  };
  const curve = report.data?.threshold_curves.find((c) => c.param === "alarm_threshold");
  const decided = (calls.data ?? []).filter(DECIDED);

  return (
    <div className="space-y-5">
      {/* title row with the actions, always in the same place */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">How strict detection is. Drag, see which calls change, then save.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {patch && <span className="flex items-center gap-1.5 text-sm font-medium text-link"><span className="size-2 rounded-full bg-primary" aria-hidden />Unsaved changes</span>}
          <Button variant="outline" disabled={!patch} onClick={() => { reset(); setMsg(null); }}>Reset</Button>
          <Button variant={patch ? "default" : "outline"} onClick={save} disabled={!patch}><Save className="size-4" aria-hidden />Save changes</Button>
        </div>
      </div>
      {isFixtures && (
        <p role="note" className="rounded-xl border border-review bg-review-bg px-3 py-2 text-xs text-review">
          MOCK: no settings files exist in fixtures. A hand-made draft is approximated over invented sample calls, and saving is disabled.
        </p>
      )}
      {(msg || applied) && (
        <p role={msg && !msg.ok ? "alert" : "status"} className={cn("rounded-xl border p-3 text-sm", msg && !msg.ok ? "border-alarm bg-alarm-bg text-alarm" : "border-ok bg-ok-bg text-ok")}>{msg?.text ?? applied}</p>
      )}

      {/* the focal panel: all three thresholds on the left (alarm big, the other two compact underneath), their effect
          on the right (stacked on narrow screens). No folds: everything that changes a decision is in view. */}
      <section aria-labelledby="alarm-h" className="elevated grid gap-6 rounded-2xl p-5 lg:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] lg:gap-8">
        <div className="min-w-0 space-y-5">
          <div className="space-y-3">
            <div className="flex items-baseline justify-between gap-4">
              <h2 id="alarm-h" className="flex items-center gap-1 text-base font-semibold"><label htmlFor="th-alarm">Alarm threshold</label><InfoTip term="alarm_threshold" /></h2>
              <p className="tabular text-3xl font-semibold tracking-tight">{pct(draft.alarm)}<span className={cn("ml-2 text-xs font-normal", patch?.thresholds?.alarm != null ? "text-link" : "text-muted-foreground")}>saved {pct(saved.data.alarm)}</span></p>
            </div>
            {calls.status === "loading" && !calls.data ? <SkeletonBlock rows={1} /> : (
              <ThresholdTrack id="th-alarm" value={draft.alarm} saved={saved.data.alarm} review={draft.review} calls={decided} after={after} onChange={(v) => set("alarm", v)} />
            )}
          </div>
          <div className="grid gap-5 border-t border-border pt-5 sm:grid-cols-2">
            <SmallSlider k="review" term="review_threshold" title="Review threshold" value={draft.review} saved={saved.data.review} onChange={(v) => set("review", v)} />
            <SmallSlider k="confidence_gate" term="confidence_gate" title="Confidence gate" value={draft.confidence_gate} saved={saved.data.confidence_gate} onChange={(v) => set("confidence_gate", v)} />
          </div>
        </div>
        <div className="min-w-0 lg:border-l lg:border-border lg:pl-8">
          <Impact calls={decided} known={new Set((calls.data ?? []).map((c) => c.call_id))} patch={patch} sim={sim} />
        </div>
      </section>

      {/* the context, one card with tabs instead of three folds at the bottom of the page */}
      <section aria-label="Context" className="surface-tint space-y-4 rounded-2xl p-5">
        <Segmented label="Context" size="sm" value={more} onChange={setMore} options={[
          { key: "tradeoff", label: "Trade-off on the test set", icon: <LineChart className="size-4" aria-hidden /> },
          { key: "suggestions", label: "Suggestions from your feedback", icon: <Lightbulb className="size-4" aria-hidden /> },
          { key: "log", label: "Change log", icon: <History className="size-4" aria-hidden /> },
        ]} />
        <div key={more} className="view-in">
          {more === "tradeoff" && (
            <div className="space-y-2">
              <p className="flex flex-wrap items-center gap-x-1 text-xs text-muted-foreground">
                Precision<InfoTip term="precision" /> and recall<InfoTip term="recall" /> at every alarm threshold
                {report.data ? `, measured on ${report.data.overall.n} ${report.data.split} calls${report.data.is_mock ? " (MOCK curve)" : ""}` : ""}. The solid line is your draft.
              </p>
              {curve ? <CurveChart curve={curve} dragged={draft.alarm} />
                : report.status === "loading" ? <div className="skeleton h-24" /> : <p className="text-sm text-muted-foreground">No curve yet: it appears after the first evaluation run.</p>}
            </div>
          )}
          {more === "suggestions" && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">Built from calls you marked as false alarm, missed or correct. Preview one to see its effect above before you apply it.</p>
              <SuggestionsCard bare key={epoch} activePatch={patch} onPreview={(p: Patch) => { setMsg(null); setApplied(null); loadPatch(saved.data!, p); }}
                onApplied={(message) => { setApplied(message); setMsg(null); reset(); saved.reload(); calls.reload(); setEpoch((e) => e + 1); }} />
            </div>
          )}
          {more === "log" && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">Who changed the settings, when, and what.</p>
              <AuditLog bare refreshKey={epoch} />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

/** The effect, always visible: plain numbers without a draft; "before → after" and the calls that change while there is one. */
function Impact({ calls, known, patch, sim }: { calls: CallListItem[]; known: Set<string>; patch: Patch | null; sim: ReturnType<typeof useSimulate> }) {
  const data = sim.data ?? sim.stale;
  const base: Record<Decision, number> = { alarm: 0, review: 0, no_alert: 0 };
  for (const c of calls) base[c.decision!] += 1;
  const drafting = !!patch && !!data;
  // Without a draft, "Right now" counts the call list itself. useSimulate keeps its last result (to avoid flicker while
  // dragging), so reading data.counts.before here would show an old simulation after Reset or Save.
  const before = drafting ? data!.counts.before : base;
  const after = drafting ? data!.counts.after : before;
  const share = (r: Record<Decision, number>) => { const n = r.alarm + r.review + r.no_alert; return n ? ((r.alarm + r.review) / n) * 100 : 0; };
  const wBefore = drafting ? data!.workload.before.flagged_per_100 : share(base);
  const wAfter = drafting ? data!.workload.after.flagged_per_100 : wBefore;
  // same icons and colours as the decisions on the Overview; "Need a person" = alarms + reviews as a share of all calls
  const items: { key: string; label: string; before: number; after: number; tone: string; icon: typeof Check; iconTone: string; unit?: string }[] = [
    { key: "alarm", label: "Alerts", before: before.alarm, after: after.alarm, tone: "text-alarm", icon: OctagonAlert, iconTone: "text-alarm" },
    { key: "review", label: "To review", before: before.review, after: after.review, tone: "text-review", icon: Eye, iconTone: "text-review" },
    { key: "no_alert", label: "No alert", before: before.no_alert, after: after.no_alert, tone: "", icon: Check, iconTone: "text-noalert" },
    { key: "workload", label: "Need a person", before: Math.round(wBefore), after: wAfter, tone: "", icon: UserRound, iconTone: "text-muted-foreground", unit: " %" },
  ];
  const fc = patch ? data?.feedback_check : null;

  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold">{patch ? "If you save" : "Right now"}</h3>
        {patch && sim.loading && <span className="text-xs text-muted-foreground">updating…</span>}
      </div>
      {patch && sim.error && !data ? <p role="alert" className="text-sm text-alarm">The effect could not be computed: {sim.error}</p> : (
        <dl className="grid grid-cols-2 gap-3">
          {items.map((it) => {
            const changed = drafting && Math.round(it.after) !== Math.round(it.before);
            return (
              <div key={it.key} className={cn("rounded-xl border bg-background/50 px-4 py-3 transition-colors duration-300",
                changed ? "border-primary/50" : "border-border")}>
                <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><it.icon className={cn("size-3.5", it.iconTone)} aria-hidden />{it.label}</dt>
                <dd className="tabular mt-1 text-2xl font-semibold tracking-tight">
                  {drafting && (
                    <><span className="text-muted-foreground">{it.before}{it.unit}</span><ArrowRight className="mx-1 inline size-3.5 text-muted-foreground" aria-label="becomes" /></>
                  )}
                  <Tween value={it.after} className={changed ? it.tone || "text-foreground" : ""} />{it.unit}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      {drafting && (
        data!.flipped.length === 0 ? <p className="text-sm text-muted-foreground">No call would change its decision.</p> : (
          <ul className="space-y-1.5 border-t border-border pt-3">
            {data!.flipped.map((f) => (
              <li key={f.call_id} className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm">
                {known.has(f.call_id)
                  ? <Link href={`/calls/${f.call_id}`} className="font-medium text-link underline-offset-2 hover:underline">{f.call_id}</Link>
                  : <span className="font-medium" title="Sample call: no detail page">{f.call_id}</span>}
                <span className="flex items-center gap-1.5"><DecisionBadge decision={f.before} size="sm" /><ArrowRight className="size-3.5 text-muted-foreground" aria-label="becomes" /><DecisionBadge decision={f.after} size="sm" /></span>
                {f.attributed_to.length > 0 && <span className="text-xs text-muted-foreground">because of the {f.attributed_to.map(componentLabel).join(" and ")}</span>}
              </li>
            ))}
          </ul>
        )
      )}
      {fc && fc.violations.length > 0 && (
        <p role="alert" className="flex gap-2 rounded-xl border border-alarm bg-alarm-bg p-3 text-sm text-alarm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />This draft changes {fc.violations.join(", ")}, which you marked as correct or which would move the wrong way.
        </p>
      )}
      {fc && fc.fixed.length > 0 && (
        <p className="flex gap-2 rounded-xl border border-ok bg-ok-bg p-3 text-sm text-ok">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />Fixes {fc.fixed.length} of your verdicts: {fc.fixed.join(", ")}.
        </p>
      )}
      {drafting && data?.baseline_version === "unknown" && (
        <p className="text-xs text-muted-foreground">This server has no detailed simulation yet, so the check against your feedback is missing.</p>
      )}
    </div>
  );
}

function SmallSlider({ k, term, title, value, saved, onChange }: {
  k: string; term: Term; title: string; value: number; saved: number; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={`th-${k}`} className="flex items-center gap-1 text-sm font-semibold">{title}<InfoTip term={term} /></label>
        <span className="tabular text-lg font-semibold">{pct(value)}<span className={cn("ml-1.5 text-xs font-normal", value !== saved ? "text-link" : "text-muted-foreground")}>saved {pct(saved)}</span></span>
      </div>
      {/* same look as the alarm slider: a thin track filled up to the value, the round violet thumb on top */}
      <div className="relative">
        <div aria-hidden className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-muted" style={{ left: 9, right: 9 }} />
        <div aria-hidden className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-primary/70" style={{ left: 9, width: `calc(${value} * (100% - 18px))` }} />
        <input id={`th-${k}`} type="range" min={0} max={1} step={0.01} value={value} onChange={(e) => onChange(+e.target.value)} className="sens-range" aria-valuetext={pct(value)} />
      </div>
    </div>
  );
}
