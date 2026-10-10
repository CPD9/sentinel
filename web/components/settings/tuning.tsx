"use client";
// Sensitivity: one focal panel (the alarm threshold, every call as a dot on it, and what changes if you save), then the
// test-set trade-off, then three one-line folds (advanced thresholds, suggestions from feedback, change log).
// The unsaved draft is shared with the suggestions' Preview via SettingsDraftProvider; nothing is saved until "Save changes".
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, Save } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { DecisionBadge } from "@/components/shell/badges";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { InfoTip } from "@/components/ui/info-tip";
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
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Sensitivity</h1>
          <p className="text-sm text-muted-foreground">How strict Sentinel is. Drag, see which calls change, then save.</p>
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

      {/* the focal panel: the slider on the left, its effect on the right (stacked on narrow screens) */}
      <section aria-labelledby="alarm-h" className="elevated grid gap-6 rounded-2xl p-5 lg:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] lg:gap-8">
        <div className="min-w-0 space-y-3">
          <div className="flex items-baseline justify-between gap-4">
            <h2 id="alarm-h" className="flex items-center gap-1 text-base font-semibold"><label htmlFor="th-alarm">Alarm threshold</label><InfoTip term="alarm_threshold" /></h2>
            <p className="tabular text-3xl font-semibold tracking-tight">{pct(draft.alarm)}<span className={cn("ml-2 text-xs font-normal", patch?.thresholds?.alarm != null ? "text-link" : "text-muted-foreground")}>saved {pct(saved.data.alarm)}</span></p>
          </div>
          {calls.status === "loading" && !calls.data ? <SkeletonBlock rows={1} /> : (
            <ThresholdTrack id="th-alarm" value={draft.alarm} saved={saved.data.alarm} review={draft.review} calls={decided} after={after} onChange={(v) => set("alarm", v)} />
          )}
        </div>
        <div className="min-w-0 lg:border-l lg:border-border lg:pl-8">
          <Impact calls={decided} patch={patch} sim={sim} />
        </div>
      </section>

      {/* the trade-off, quieter */}
      <section aria-labelledby="tradeoff-h" className="surface-tint space-y-2 rounded-2xl p-5">
        <h3 id="tradeoff-h" className="text-sm font-semibold">How strictness trades off on the test set</h3>
        <p className="flex flex-wrap items-center gap-x-1 text-xs text-muted-foreground">
          Precision<InfoTip term="precision" /> and recall<InfoTip term="recall" /> at every alarm threshold
          {report.data ? `, measured on ${report.data.overall.n} ${report.data.split} calls${report.data.is_mock ? " (MOCK curve)" : ""}` : ""}. The solid line is your draft.
        </p>
        {curve ? <CurveChart curve={curve} dragged={draft.alarm} />
          : report.status === "loading" ? <div className="skeleton h-24" /> : <p className="text-sm text-muted-foreground">No curve yet: it appears after the first evaluation run.</p>}
      </section>

      <Fold title="Advanced" hint={`review threshold ${pct(draft.review)}, confidence gate ${pct(draft.confidence_gate)}`}>
        <div className="grid gap-6 md:grid-cols-2">
          <SmallSlider k="review" term="review_threshold" title="Review threshold" help="From this risk up to the alarm threshold, a person decides." value={draft.review} saved={saved.data.review} onChange={(v) => set("review", v)} />
          <SmallSlider k="confidence_gate" term="confidence_gate" title="Confidence gate" help="Below this confidence, a call with some risk always goes to a person." value={draft.confidence_gate} saved={saved.data.confidence_gate} onChange={(v) => set("confidence_gate", v)} />
        </div>
      </Fold>
      <Fold title="Suggested changes from your feedback" hint="built from calls you marked as false alarm, missed or correct">
        <SuggestionsCard bare key={epoch} activePatch={patch} onPreview={(p: Patch) => { setMsg(null); setApplied(null); loadPatch(saved.data!, p); }}
          onApplied={(message) => { setApplied(message); setMsg(null); reset(); saved.reload(); calls.reload(); setEpoch((e) => e + 1); }} />
      </Fold>
      <Fold title="Change log" hint="who changed the settings, when, and what">
        <AuditLog bare refreshKey={epoch} />
      </Fold>
    </div>
  );
}

/** The effect, always visible: plain numbers without a draft; "before → after" and the calls that change while there is one. */
function Impact({ calls, patch, sim }: { calls: CallListItem[]; patch: Patch | null; sim: ReturnType<typeof useSimulate> }) {
  const data = sim.data ?? sim.stale;
  const base: Record<Decision, number> = { alarm: 0, review: 0, no_alert: 0 };
  for (const c of calls) base[c.decision!] += 1;
  const drafting = !!patch && !!data;
  const before = data?.counts.before ?? base;
  const after = drafting ? data!.counts.after : before;
  const share = (r: Record<Decision, number>) => { const n = r.alarm + r.review + r.no_alert; return n ? ((r.alarm + r.review) / n) * 100 : 0; };
  const wBefore = data?.workload.before.flagged_per_100 ?? share(base);
  const wAfter = drafting ? data!.workload.after.flagged_per_100 : wBefore;
  const items: { key: string; label: string; before: number; after: number; tone: string; unit?: string }[] = [
    { key: "alarm", label: "Alarms", before: before.alarm, after: after.alarm, tone: "text-alarm" },
    { key: "review", label: "To review", before: before.review, after: after.review, tone: "text-review" },
    { key: "no_alert", label: "No alert", before: before.no_alert, after: after.no_alert, tone: "" },
    { key: "workload", label: "Need a person", before: Math.round(wBefore), after: wAfter, tone: "", unit: " %" },
  ];
  const fc = patch ? data?.feedback_check : null;

  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold">{patch ? "If you save" : "Right now"}</h3>
        {patch && sim.loading && <span className="text-xs text-muted-foreground">updating…</span>}
      </div>
      {patch && sim.error && !data ? <p role="alert" className="text-sm text-alarm">The effect could not be computed: {sim.error}</p> : (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
          {items.map((it) => {
            const changed = drafting && Math.round(it.after) !== Math.round(it.before);
            return (
              <div key={it.key}>
                <dt className="text-xs text-muted-foreground">{it.label}</dt>
                <dd className="tabular text-xl font-semibold tracking-tight">
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
                <Link href={`/calls/${f.call_id}`} className="font-medium text-link underline-offset-2 hover:underline">{f.call_id}</Link>
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

function SmallSlider({ k, term, title, help, value, saved, onChange }: {
  k: string; term: Term; title: string; help: string; value: number; saved: number; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={`th-${k}`} className="flex items-center gap-1 text-sm font-semibold">{title}<InfoTip term={term} /></label>
        <span className="tabular text-lg font-semibold">{pct(value)}<span className={cn("ml-1.5 text-xs font-normal", value !== saved ? "text-link" : "text-muted-foreground")}>saved {pct(saved)}</span></span>
      </div>
      <input id={`th-${k}`} type="range" min={0} max={1} step={0.01} value={value} onChange={(e) => onChange(+e.target.value)} className="w-full" aria-valuetext={pct(value)} />
      <p className="text-xs text-muted-foreground">{help}</p>
    </div>
  );
}

function Fold({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-2xl border border-border">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1 px-5 py-3.5 text-sm font-semibold [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-4 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
        {title}<span className="font-normal text-muted-foreground">{hint}</span>
      </summary>
      <div className="border-t border-border p-5">{children}</div>
    </details>
  );
}
