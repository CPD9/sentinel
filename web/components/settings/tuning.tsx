"use client";
import { Save } from "lucide-react";
import { useState } from "react";
import { CriterionChip } from "@/components/shell/badges";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, getKeywords, getQualityReport, getQualityReports, getRules, getThresholds, saveDraft } from "@/lib/data";
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
const HELP: Record<keyof Thresholds, string> = {
  alarm: "Risk at or above this, with validated evidence and enough confidence, is an alarm.",
  review: "Risk from here up to the alarm threshold goes to review.",
  confidence_gate: "Below this confidence a call is never a confident alarm or no-alert: it goes to review.",
};

export function Tuning() {
  const saved = useAsync(getThresholds, "thresholds");
  const keywords = useAsync(getKeywords, "switch-keywords");
  const rules = useAsync(getRules, "switch-rules");
  const report = useAsync(async () => { const r = await getQualityReports(); return r.length ? getQualityReport(r[0].report_id) : null; }, "tuning-report");
  const { draft: d, setThreshold, toggleFamily, toggleRule, loadPatch, reset, toPatch } = useSettingsDraft();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [epoch, setEpoch] = useState(0);              // bumps after a save/apply so suggestions and the audit log reload

  const draft = d.thresholds ?? saved.data;
  const patch = toPatch(saved.data);
  const sim = useSimulate(patch);

  if (saved.status === "error" && !saved.data) return <ErrorCard error={saved.error} onRetry={saved.reload} />;
  if (!draft) return <SkeletonBlock rows={6} />;

  const set = (k: keyof Thresholds, v: number) => { setMsg(null); setThreshold(saved.data!, k, v); };
  const save = async () => {
    if (!patch) return;
    try {
      const r = await saveDraft(patch);
      setMsg({ ok: true, text: `Saved. Re-running ${r.rerun.stages.join(" → ")} for ${r.rerun.n_calls} calls from cache.` });
      reset(); saved.reload(); keywords.reload(); rules.reload(); setEpoch((e) => e + 1);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : `${e.code}: ${e.detail}`) : String(e) });
    }
  };

  return (
    <div className="space-y-4">
      <SuggestionsCard key={epoch} activePatch={patch} onPreview={(p) => { setMsg(null); loadPatch(saved.data!, p); }} onApplied={() => { reset(); saved.reload(); keywords.reload(); rules.reload(); setEpoch((e) => e + 1); }} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <div className="min-w-0 space-y-4">
          {(Object.keys(draft) as (keyof Thresholds)[]).map((k) => {
            const curve = report.data?.threshold_curves.find((c) => c.param === PARAM[k]);
            return (
              <Card key={k}>
                <CardHeader>
                  <div><CardTitle><label htmlFor={`th-${k}`}>{k.replaceAll("_", " ")}</label></CardTitle><CardDescription>{HELP[k]}</CardDescription></div>
                  <div className="tabular text-lg font-semibold">{draft[k].toFixed(2)} <span className="text-xs font-normal text-muted-foreground">saved {saved.data![k].toFixed(2)}</span></div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <input id={`th-${k}`} type="range" min={0} max={1} step={0.01} value={draft[k]} onChange={(e) => set(k, +e.target.value)} className="w-full" aria-valuetext={pct(draft[k])} />
                  {curve ? (
                    <div><p className="text-xs text-muted-foreground">Precision / recall on the {report.data!.split} split ({curve.convention.replace("_", " ")}), n = {report.data!.overall.n}{report.data!.is_mock ? " — MOCK curve" : ""}.</p><CurveChart curve={curve} dragged={draft[k]} /></div>
                  ) : report.status === "loading" ? <div className="skeleton h-24" /> : <p className="text-xs text-muted-foreground">No threshold curve available for this parameter (no evaluation run yet).</p>}
                </CardContent>
              </Card>
            );
          })}

          <Card>
            <CardHeader><div><CardTitle>Detection switches (what-if)</CardTitle>
              <CardDescription>Switch a keyword family or a whole rule off to see the effect on the right. A switch stays a draft until you save.</CardDescription></div></CardHeader>
            <CardContent className="space-y-4">
              {keywords.data && (
                <fieldset><legend className="mb-1 text-xs font-medium text-muted-foreground">Keyword families</legend>
                  <ul className="grid gap-1.5 sm:grid-cols-2">{Object.entries(keywords.data.families).map(([name, f]) => (
                    <li key={name}><label className="flex flex-wrap items-center gap-2 text-sm"><input type="checkbox" checked={d.families.includes(name)} onChange={() => { setMsg(null); toggleFamily(name); }} />
                      <span className="font-mono text-xs">{name}</span> <CriterionChip criterion={f.criterion} />off</label></li>
                  ))}</ul></fieldset>
              )}
              {rules.data && (
                <fieldset><legend className="mb-1 text-xs font-medium text-muted-foreground">Rules</legend>
                  <ul className="grid gap-1.5 sm:grid-cols-2">{rules.data.rules.map((r) => (
                    <li key={r.criterion}>{r.enabled
                      ? <label className="flex flex-wrap items-center gap-2 text-sm"><input type="checkbox" checked={d.rules.includes(r.criterion)} onChange={() => { setMsg(null); toggleRule(r.criterion); }} /><CriterionChip criterion={r.criterion} />off</label>
                      : <span className="flex items-center gap-2 text-sm text-muted-foreground"><CriterionChip criterion={r.criterion} />already disabled</span>}</li>
                  ))}</ul></fieldset>
              )}
              {!keywords.data && !rules.data && <SkeletonBlock rows={2} />}
            </CardContent>
          </Card>
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
