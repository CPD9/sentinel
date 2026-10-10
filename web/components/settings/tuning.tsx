"use client";
import { ArrowRight, Save } from "lucide-react";
import { useState } from "react";
import { DecisionBadge } from "@/components/shell/badges";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, getQualityReport, getQualityReports, getThresholds, putThresholds } from "@/lib/data";
import { pct } from "@/lib/format";
import type { Decision, Thresholds } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { usePreview } from "@/lib/use-preview";
import { CurveChart } from "./curve-chart";

const GAP = 0.01;
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
  const report = useAsync(async () => { const r = await getQualityReports(); return r.length ? getQualityReport(r[0].report_id) : null; }, "tuning-report");
  const [edited, setDraft] = useState<Thresholds | null>(null);
  const draft = edited ?? saved.data;
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const dirty = !!draft && !!saved.data && (Object.keys(draft) as (keyof Thresholds)[]).some((k) => draft[k] !== saved.data![k]);
  const preview = usePreview(draft ? { thresholds: draft } : null);

  if (saved.status === "error" && !saved.data) return <ErrorCard error={saved.error} onRetry={saved.reload} />;
  if (!draft) return <SkeletonBlock rows={6} />;

  const set = (k: keyof Thresholds, v: number) => {
    setMsg(null);
    setDraft((prev) => {
      const d = prev ?? saved.data!;
      const n = { ...d, [k]: Math.round(v * 100) / 100 };
      if (k === "alarm") n.alarm = Math.max(n.alarm, n.review + GAP);
      if (k === "review") n.review = Math.min(n.review, n.alarm - GAP);
      return n;
    });
  };
  const save = async () => {
    try {
      const r = await putThresholds(draft);
      setMsg({ ok: true, text: `Saved. Re-running ${r.rerun.stages.join(" → ")} for ${r.rerun.n_calls} calls from cache.` });
      setDraft(null);
      saved.reload();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : `${e.code}: ${e.detail}`) : String(e) });
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="space-y-4">
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
      </div>

      <aside className="space-y-4 xl:sticky xl:top-16 xl:self-start">
        <Card>
          <CardHeader><CardTitle>Impact (preview, nothing saved)</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {preview.error && !preview.data ? <p className="text-sm text-muted-foreground">preview unavailable — {preview.error}</p> : !preview.data ? <SkeletonBlock rows={3} /> : (
              <>
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 font-medium">Decision</th><th className="font-medium">Before</th><th /><th className="font-medium">After</th></tr></thead>
                  <tbody>{(["alarm", "review", "no_alert"] as Decision[]).map((d) => (
                    <tr key={d} className="border-t border-border"><td className="py-1.5"><DecisionBadge decision={d} size="sm" /></td>
                      <td className="tabular">{preview.data!.decision_counts.before[d] ?? 0}</td><td className="text-muted-foreground"><ArrowRight className="size-3" /></td>
                      <td className="tabular font-semibold">{preview.data!.decision_counts.after[d] ?? 0}</td></tr>
                  ))}</tbody>
                </table>
                {preview.data.changed.length === 0 ? <p className="text-sm text-muted-foreground">No call would change its decision.</p> : (
                  <ul className="space-y-1.5 text-sm">{preview.data.changed.map((c) => (
                    <li key={c.call_id} className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs">{c.call_id}</span><DecisionBadge decision={c.decision_before} size="sm" /><ArrowRight className="size-3" /><DecisionBadge decision={c.decision_after} size="sm" /></li>
                  ))}</ul>
                )}
                {preview.loading && <p className="text-xs text-muted-foreground">updating…</p>}
                <p className="text-[11px] text-muted-foreground">Counts cover calls that already have a decision.</p>
              </>
            )}
          </CardContent>
        </Card>
        <div className="flex gap-2">
          <Button onClick={save} disabled={!dirty}><Save className="size-4" />Save thresholds</Button>
          <Button variant="outline" disabled={!dirty} onClick={() => { setDraft(null); setMsg(null); }}>Reset</Button>
        </div>
        {msg && <p role={msg.ok ? "status" : "alert"} className={`rounded-md border p-3 text-sm ${msg.ok ? "border-ok bg-ok-bg text-ok" : "border-alarm bg-alarm-bg text-alarm"}`}>{msg.text}</p>}
        <p className="text-xs text-muted-foreground">Saving re-runs rules, confidence and decision from cached transcripts and extractions. Nothing is re-transcribed.</p>
      </aside>
    </div>
  );
}

