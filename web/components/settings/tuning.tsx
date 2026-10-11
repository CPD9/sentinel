"use client";
// Settings → Threshold (Nik's design 05): presets and the alert line with every call on it | what the change would do
// (Now / After, the calls that flip, workload, Save / Reset), then the
// test-set trade-off, then three one-line folds (advanced thresholds, suggestions from feedback, change log).
// The unsaved draft is shared with the suggestions' Preview via SettingsDraftProvider; nothing is saved until "Save changes".
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, Save } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { DecisionBadge } from "@/components/shell/badges";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { InfoTip } from "@/components/ui/info-tip";
import { Tween } from "@/components/ui/tween";
import { ApiError, getCalls, getQualityReport, getQualityReports, getSuggestions, getThresholds, isFixtures, isLocalRun, saveDraft } from "@/lib/data";
import { DECISION_LABEL, score } from "@/lib/explain";
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
import { WorkloadMeter } from "./workload-meter";
import { PRESETS } from "@/lib/presets";
import { OutcomeCounts } from "@/components/quality/outcome-counts";

const errText = (e: unknown) => (e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : `${e.code}: ${e.detail}`) : String(e));
const DECIDED = (c: CallListItem) => (c.status === "done" || c.status === "error") && c.decision != null;

export function Tuning() {
  const saved = useAsync(getThresholds, "thresholds");
  const calls = useAsync(getCalls, "calls");
  const suggestions = useAsync(() => getSuggestions(), "tuning-suggestions-probe");
  const report = useAsync(async () => { const r = await getQualityReports(); return r.length ? getQualityReport(r[0].report_id) : null; }, "tuning-report");
  const { draft: d, setThreshold, loadPatch, reset, toPatch } = useSettingsDraft();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [applied, setApplied] = useState<string | null>(null);   // lives here, not in the keyed card, so a remount cannot clear it
  const [epoch, setEpoch] = useState(0);              // bumps after a save/apply so suggestions and the change log reload

  const draft = d.thresholds ?? saved.data;
  // Demo path: /settings/threshold?draft_alarm=0.5 opens with that alert line as an unsaved draft (nothing is saved).
  const params = useSearchParams();
  const wanted = params.get("draft_alarm");
  const appliedDraft = useRef(false);
  useEffect(() => {
    if (appliedDraft.current || !wanted || !saved.data) return;
    appliedDraft.current = true;
    const v = Number(wanted);
    if (v > saved.data.review && v <= 1) setThreshold(saved.data, "alarm", v);
  }, [wanted, saved.data, setThreshold]);
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
  const curve = report.data?.threshold_curves?.find((c) => c.param === "alarm_threshold");
  const decided = (calls.data ?? []).filter(DECIDED);

  const readOnly = isFixtures || isLocalRun;
  const saveTitle = isLocalRun ? "Read-only local run: saving needs the API" : isFixtures ? "Disabled in fixtures mode (MOCK)" : undefined;

  return (
    <div className="space-y-5">
      <h2 className="sr-only">Threshold</h2>
      {isFixtures && (
        <p role="note" className="rounded-xl border border-review bg-review-bg px-3 py-2 text-xs text-review">
          MOCK: no settings files exist in fixtures. A hand-made draft is approximated over invented sample calls, and saving is disabled.
        </p>
      )}
      {(msg || applied) && (
        <p role={msg && !msg.ok ? "alert" : "status"} className={cn("rounded-xl border p-3 text-sm", msg && !msg.ok ? "border-alarm bg-alarm-bg text-alarm" : "border-ok bg-ok-bg text-ok")}>{msg?.text ?? applied}</p>
      )}

      {/* Nik's design 05: the line on the left, what the change would do on the right */}
      <div className="grid gap-5 lg:grid-cols-2">
        <section aria-labelledby="alarm-h" className="elevated stage-in min-w-0 space-y-6 rounded-[var(--radius-panel)] p-6">
          <div className="space-y-3">
            <h3 className="eyebrow">Sensitivity preset</h3>
            <div role="group" aria-label="Sensitivity preset" className="flex flex-wrap gap-3">
              {PRESETS.map((pr) => {
                const on = Math.abs(draft.alarm - pr.alarm) < 0.005;
                return (
                  <button key={pr.label} type="button" aria-pressed={on} title={`Alert line ${score(pr.alarm)}: ${pr.hint}`} onClick={() => set("alarm", Math.max(pr.alarm, draft.review + 0.01))}
                    className={cn("h-11 rounded-full border px-6 text-body font-semibold transition-colors duration-[var(--dur-fast)]", on ? "border-primary bg-primary text-primary-foreground" : "border-foreground/60 hover:bg-muted")}>
                    {pr.label}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="space-y-3">
            <div className="flex items-baseline justify-between gap-4">
              <h3 id="alarm-h" className="eyebrow flex items-center gap-1"><label htmlFor="th-alarm">Where calls fall by risk score</label><InfoTip term="alarm_threshold" /></h3>
              <p className="tabular text-headline font-semibold tracking-tight"><span className="text-body font-normal text-muted-foreground">alert line </span><Tween value={draft.alarm * 100} /></p>
            </div>
            {calls.status === "loading" && !calls.data ? <SkeletonBlock rows={1} /> : (
              <ThresholdTrack id="th-alarm" value={draft.alarm} saved={saved.data.alarm} review={draft.review} calls={decided} after={after} onChange={(v) => set("alarm", v)} />
            )}
          </div>
          <p className="text-body leading-relaxed">
            <b>No alert</b> below {score(draft.review)}. <b>Review</b> from {score(draft.review)} to {score(draft.alarm)}: the system is unsure and a person decides.{" "}
            <b>Alert</b> at {score(draft.alarm)} and above. <span className="text-muted-foreground">Saved setting: {score(saved.data.alarm)}.</span>
          </p>
        </section>

        <section aria-label="What this change would do" className="elevated stage-in flex min-w-0 flex-col gap-5 rounded-[var(--radius-panel)] p-6" style={{ "--i": 1 } as React.CSSProperties}>
          <Impact calls={decided} known={new Set((calls.data ?? []).map((c) => c.call_id))} patch={patch} sim={sim} />
          <div className="mt-auto flex flex-wrap items-center gap-3 border-t border-border pt-5">
            <button type="button" onClick={save} disabled={!patch || readOnly} title={saveTitle}
              className="inline-flex h-11 items-center gap-2 rounded-full bg-primary px-6 font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40">
              <Save className="size-4" aria-hidden />Save thresholds
            </button>
            <button type="button" onClick={() => { reset(); setMsg(null); }} disabled={!patch}
              className="inline-flex h-11 items-center rounded-full border border-foreground/60 px-6 font-semibold hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40">Reset</button>
            {patch && <span className="text-sm text-muted-foreground">Unsaved draft{readOnly ? ` · ${saveTitle}` : ""}</span>}
          </div>
        </section>
      </div>

      <OutcomeCounts />

      {/* the trade-off, only when a curve exists: an empty chart is a stagnant control */}
      {curve && <section aria-labelledby="tradeoff-h" className="surface-tint space-y-2 rounded-2xl p-5">
        <h3 id="tradeoff-h" className="text-sm font-semibold">How strictness trades off on the test set</h3>
        <p className="flex flex-wrap items-center gap-x-1 text-xs text-muted-foreground">
          Precision<InfoTip term="precision" /> and recall<InfoTip term="recall" /> at every alert line
          {report.data ? `, measured on ${report.data.overall.n} ${report.data.split} calls${report.data.is_mock ? " (MOCK curve)" : ""}` : ""}. The solid line is your draft.
        </p>
        <CurveChart curve={curve} dragged={draft.alarm} />
      </section>}

      <Fold title="Advanced" hint={`review line ${score(draft.review)}, confidence gate ${score(draft.confidence_gate)}`}>
        <div className="grid gap-6 md:grid-cols-2">
          <SmallSlider k="review" term="review_threshold" title="Review line" help="From this risk up to the alert line, a person decides." value={draft.review} saved={saved.data.review} onChange={(v) => set("review", v)} />
          <SmallSlider k="confidence_gate" term="confidence_gate" title="Confidence gate" help="Below this confidence, a call with some risk always goes to a person." value={draft.confidence_gate} saved={saved.data.confidence_gate} onChange={(v) => set("confidence_gate", v)} />
        </div>
      </Fold>
      {/* Suggestions need the API's suggestion search; the change log needs saving. Neither exists in the read-only local
          run, so they are not shown there (never a dead control). */}
      {!isLocalRun && suggestions.status !== "error" && (
        <Fold title="Suggested changes from your feedback" hint="built from calls you marked as false alarm, missed or correct">
          <SuggestionsCard bare key={epoch} activePatch={patch} onPreview={(p: Patch) => { setMsg(null); setApplied(null); loadPatch(saved.data!, p); }}
            onApplied={(message) => { setApplied(message); setMsg(null); reset(); saved.reload(); calls.reload(); setEpoch((e) => e + 1); }} />
        </Fold>
      )}
      {!readOnly && (
        <Fold title="Change log" hint="who changed the settings, when, and what">
          <AuditLog bare refreshKey={epoch} />
        </Fold>
      )}
      {isLocalRun && <p className="text-xs text-muted-foreground">Read-only local run: suggestions from officer feedback and the change log need the API with saving; they appear there.</p>}
    </div>
  );
}


/** Nik's design 05, right panel: Outcome | Now | After, one sentence per kind of move, the calls that flip, the workload. */
function Impact({ calls, known, patch, sim }: { calls: CallListItem[]; known: Set<string>; patch: Patch | null; sim: ReturnType<typeof useSimulate> }) {
  const data = sim.data ?? sim.stale;
  const base: Record<Decision, number> = { alarm: 0, review: 0, no_alert: 0 };
  for (const c of calls) base[c.decision!] += 1;
  const drafting = !!patch && !!data;
  // Without a draft, "Now" counts the call list itself. useSimulate keeps its last result (to avoid flicker while
  // dragging), so reading data.counts.before here would show an old simulation after Reset or Save.
  const before = drafting ? data!.counts.before : base;
  const after = drafting ? data!.counts.after : before;
  const rows: { key: Decision; label: string; tone: string }[] = [
    { key: "alarm", label: "Alert", tone: "text-alarm" }, { key: "review", label: "Review", tone: "text-review" }, { key: "no_alert", label: "No alert", tone: "" },
  ];
  const moves = new Map<string, number>();
  for (const f of drafting ? data!.flipped : []) moves.set(`${f.before}>${f.after}`, (moves.get(`${f.before}>${f.after}`) ?? 0) + 1);
  const fc = patch ? data?.feedback_check : null;
  const w = drafting ? data!.workload : null;

  return (
    <div className="space-y-4" aria-live="polite">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="eyebrow">What this change would do</h3>
        {patch && sim.loading && <span className="text-xs text-muted-foreground">updating…</span>}
      </div>
      {patch && sim.error && !data ? <p role="alert" className="text-sm text-alarm">The effect could not be computed: {sim.error}</p> : (
        <table className="w-full text-lead">
          <thead><tr className="border-b border-border text-left text-sm text-muted-foreground"><th className="py-2 font-normal">Outcome</th><th className="w-24 py-2 font-normal">Now</th><th className="w-24 py-2 font-normal">After</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const changed = before[r.key] !== after[r.key];
              return (
                <tr key={r.key} className="border-b border-border/60">
                  <th scope="row" className={cn("py-3 text-left font-semibold", r.tone)}>{r.label}</th>
                  <td className="tabular py-3">{before[r.key]}</td>
                  <td className={cn("tabular py-3 font-semibold", changed && (r.tone || "text-foreground"))}><Tween value={after[r.key]} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {!patch ? <p className="text-sm text-muted-foreground">Move the alert line or pick a preset: every call of this run is decided again with the draft, nothing is saved.</p>
        : drafting && data!.flipped.length === 0 ? <p className="text-body">No call would change its decision.</p>
        : drafting && (
          <>
            <p className="text-body">
              {[...moves].map(([k, n], i) => {
                const [b, a] = k.split(">") as [Decision, Decision];
                return <span key={k}>{i > 0 && " "}<b>{n} call{n === 1 ? "" : "s"} move{n === 1 ? "s" : ""} from {DECISION_LABEL[b]} to {DECISION_LABEL[a]}.</b></span>;
              })}
              {fc && fc.n_feedback > 0 && <span className="text-muted-foreground"> On calls already checked by a person: {fc.fixed.length} fixed, {fc.violations.length} moved the wrong way.</span>}
            </p>
            <ul className="max-h-48 space-y-1.5 overflow-y-auto border-t border-border pt-3">
              {data!.flipped.map((f, i) => (
                <li key={`${f.call_id}-${f.after}`} className="stage-in flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm" style={{ "--i": Math.min(i, 8) } as React.CSSProperties}>
                  {known.has(f.call_id)
                    ? <Link href={`/calls/${f.call_id}`} className="font-mono font-medium underline-offset-2 hover:underline">{f.call_id}</Link>
                    : <span className="font-mono font-medium" title="Sample call: no detail page">{f.call_id}</span>}
                  <span className="flex items-center gap-1.5"><DecisionBadge decision={f.before} size="sm" /><ArrowRight className="size-3.5 text-muted-foreground" aria-label="becomes" /><DecisionBadge decision={f.after} size="sm" /></span>
                  <span className="tabular text-xs text-muted-foreground">risk {score(f.risk_after)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      {w && <WorkloadMeter before={w.before} after={w.after} delta={w.delta_flagged_per_100} />}
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
      <p className="text-xs text-muted-foreground">
        {isLocalRun ? "Preview re-decides the calls of this run with the pipeline’s own decision code (exact), not the final test set."
          : drafting && data?.baseline_version === "unknown" ? "This server has no detailed simulation yet, so the check against your feedback is missing."
          : "Preview uses the calls already processed, not the final test set."}
      </p>
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
        <span className="tabular text-lg font-semibold">{score(value)}<span className={cn("ml-1.5 text-xs font-normal", value !== saved ? "text-foreground" : "text-muted-foreground")}>saved {score(saved)}</span></span>
      </div>
      <input id={`th-${k}`} type="range" min={0} max={1} step={0.01} value={value} onChange={(e) => onChange(+e.target.value)} className="w-full" aria-valuetext={score(value)} />
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
