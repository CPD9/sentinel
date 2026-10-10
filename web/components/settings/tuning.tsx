"use client";
import { ChevronRight, Save } from "lucide-react";
import { useState } from "react";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, getQualityReport, getQualityReports, getThresholds, saveDraft } from "@/lib/data";
import { pct } from "@/lib/format";
import { useSettingsDraft } from "@/lib/settings-draft";
import type { Thresholds } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { useSimulate } from "@/lib/use-simulate";
import { AuditLog } from "./audit-log";
import { CurveChart } from "./curve-chart";
import { ImpactPanel } from "./impact-panel";
import { SuggestionsCard } from "./suggestions-card";

const PARAM: Record<keyof Thresholds, "alarm_threshold" | "review_threshold" | "confidence_gate"> = {
  alarm: "alarm_threshold", review: "review_threshold", confidence_gate: "confidence_gate",
};
const TITLE: Record<keyof Thresholds, string> = {
  alarm: "Alarm threshold", review: "Review threshold", confidence_gate: "Confidence gate",
};
const HELP: Record<keyof Thresholds, string> = {
  alarm: "How much risk before SENTINEL raises an alarm (only with verified evidence and enough confidence). Lower catches more cases but gives more false alarms; higher gives fewer false alarms but misses more.",
  review: "From this risk up to the alarm threshold, a call is handed to a person for review instead of being dropped.",
  confidence_gate: "If SENTINEL is less sure than this (unclear audio, unverified evidence), it never decides alone: the call goes to review.",
};

export function Tuning() {
  const saved = useAsync(getThresholds, "thresholds");
  const report = useAsync(async () => { const r = await getQualityReports(); return r.length ? getQualityReport(r[0].report_id) : null; }, "tuning-report");
  const { draft: d, setThreshold, loadPatch, reset, toPatch } = useSettingsDraft();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [applied, setApplied] = useState<string | null>(null);   // lives here, not in the keyed card, so a remount cannot clear it
  const [epoch, setEpoch] = useState(0);              // bumps after a save/apply so suggestions and the audit log reload

  const draft = d.thresholds ?? saved.data;
  const patch = toPatch(saved.data);
  const sim = useSimulate(patch);

  if (saved.status === "error" && !saved.data) return <ErrorCard error={saved.error} onRetry={saved.reload} />;
  if (!draft) return <SkeletonBlock rows={6} />;

  const set = (k: keyof Thresholds, v: number) => { setMsg(null); setThreshold(saved.data!, k, v); };

  /** One threshold: plain title + help, the slider, and its precision / recall curve from the latest quality report. */
  const slider = (k: keyof Thresholds, main = false) => {
    const curve = report.data?.threshold_curves.find((c) => c.param === PARAM[k]);
    return (
      <Card key={k} className={main ? "rounded-2xl" : ""}>
        <CardHeader>
          <div className="max-w-prose"><CardTitle className={main ? "text-base" : ""}><label htmlFor={`th-${k}`}>{TITLE[k]}</label></CardTitle><CardDescription>{HELP[k]}</CardDescription></div>
          <div className={main ? "tabular text-3xl font-semibold tracking-tight" : "tabular text-lg font-semibold"}>{pct(draft[k])} <span className="text-xs font-normal text-muted-foreground">saved {pct(saved.data![k])}</span></div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <input id={`th-${k}`} type="range" min={0} max={1} step={0.01} value={draft[k]} onChange={(e) => set(k, +e.target.value)} className="w-full" aria-valuetext={pct(draft[k])} />
            {main && <div className="mt-1 flex justify-between text-xs text-muted-foreground"><span>← catches more (more false alarms)</span><span>stricter (fewer false alarms) →</span></div>}
          </div>
          {curve ? (
            <div><p className="text-xs text-muted-foreground">Precision / recall on the {report.data!.split} split ({curve.convention.replace("_", " ")}), n = {report.data!.overall.n}{report.data!.is_mock ? " — MOCK curve" : ""}.</p><CurveChart curve={curve} dragged={draft[k]} /></div>
          ) : report.status === "loading" ? <div className="skeleton h-24" /> : <p className="text-xs text-muted-foreground">No threshold curve available for this parameter (no evaluation run yet).</p>}
        </CardContent>
      </Card>
    );
  };
  const save = async () => {
    if (!patch) return;
    try {
      const r = await saveDraft(patch);
      setMsg({ ok: true, text: `Saved. Re-running ${r.rerun.stages.join(" → ")} for ${r.rerun.n_calls} calls from cache.` });
      reset(); saved.reload(); setEpoch((e) => e + 1);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : `${e.code}: ${e.detail}`) : String(e) });
    }
  };

  return (
    <div className="space-y-4">
      {applied && <p role="status" className="rounded-md border border-ok bg-ok-bg p-3 text-sm text-ok">{applied}</p>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <div className="min-w-0 space-y-4">
          {slider("alarm", true)}
          <details className="group rounded-2xl border border-border bg-card/40">
            <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-4 transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden />
              Advanced
              <span className="font-normal text-muted-foreground">· review threshold {pct(draft.review)} · confidence gate {pct(draft.confidence_gate)}</span>
            </summary>
            <div className="space-y-4 border-t border-border p-4">
              {slider("review")}
              {slider("confidence_gate")}
            </div>
          </details>

          <SuggestionsCard key={epoch} activePatch={patch} onPreview={(p) => { setMsg(null); setApplied(null); loadPatch(saved.data!, p); }}
            onApplied={(message) => { setApplied(message); reset(); saved.reload(); setEpoch((e) => e + 1); }} />
        </div>

        <aside className="min-w-0 space-y-4 xl:sticky xl:top-16 xl:self-start">
          <ImpactPanel patch={patch} sim={sim} />
          <div className="flex gap-2">
            <Button onClick={save} disabled={!patch}><Save className="size-4" />Save changes</Button>
            <Button variant="outline" disabled={!patch} onClick={() => { reset(); setMsg(null); }}>Reset draft</Button>
          </div>
          {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded-md border p-3 text-sm ${msg.ok ? "border-ok bg-ok-bg text-ok" : "border-alarm bg-alarm-bg text-alarm"}`}>{msg.text}</p>}
          <p className="text-xs text-muted-foreground">Saving re-runs rules, confidence and decision from cached transcripts and extractions. Nothing is re-transcribed.</p>
        </aside>
      </div>
      <AuditLog refreshKey={epoch} />
    </div>
  );
}
