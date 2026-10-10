"use client";
import { AlertTriangle, ArrowDown, ArrowRight, ArrowUp, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { DecisionBadge } from "@/components/shell/badges";
import { SkeletonBlock } from "@/components/shell/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isFixtures } from "@/lib/data";
import { VERDICT_LABEL, componentLabel } from "@/lib/format";
import type { Decision, Patch } from "@/lib/types";
import type { useSimulate } from "@/lib/use-simulate";
import { WorkloadMeter } from "./workload-meter";

/** Fixture sample calls (call_MOCK_101..) have no detail documents, so they are shown without a link. */
const sampleOnly = (id: string) => isFixtures && /^call_MOCK_1\d\d$/.test(id);

/** Live before/after: decision counts, workload, flipped calls with the reasons. Nothing here is saved. */
export function ImpactPanel({ patch, sim }: { patch: Patch | null; sim: ReturnType<typeof useSimulate> }) {
  const data = sim.data ?? sim.stale;
  return (
    <Card>
      <CardHeader><CardTitle>Impact of your draft (nothing saved)</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {!patch ? <p className="text-sm text-muted-foreground">Drag a slider or switch a keyword family or rule off to see which calls would change.</p>
          : sim.error && !data ? <p role="alert" className="text-sm text-alarm">Impact unavailable: {sim.error}</p>
          : !data ? <SkeletonBlock rows={4} />
          : <Body data={data} loading={sim.loading} error={sim.error} />}
      </CardContent>
    </Card>
  );
}

function Body({ data, loading, error }: { data: NonNullable<ReturnType<typeof useSimulate>["data"]>; loading: boolean; error: string | null }) {
  const fc = data.feedback_check;
  return (
    <div className={loading ? "opacity-60 transition-opacity" : ""} aria-busy={loading}>
      {error && <p role="alert" className="mb-2 text-xs text-alarm">Latest update failed ({error}); showing the previous result.</p>}
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 font-medium">Decision</th><th className="font-medium">Now</th><th /><th className="font-medium">With draft</th></tr></thead>
        <tbody>{(["alarm", "review", "no_alert"] as Decision[]).map((d) => (
          <tr key={d} className="border-t border-border"><td className="py-1.5"><DecisionBadge decision={d} size="sm" /></td>
            <td className="tabular">{data.counts.before[d]}</td><td className="text-muted-foreground"><ArrowRight className="size-3" aria-hidden /></td>
            <td className="tabular font-semibold">{data.counts.after[d]}</td></tr>
        ))}</tbody>
      </table>

      <div className="mt-4"><WorkloadMeter before={data.workload.before} after={data.workload.after} delta={data.workload.delta_flagged_per_100} /></div>

      {fc && fc.violations.length > 0 && (
        <p role="alert" className="mt-4 flex gap-2 rounded-md border border-alarm bg-alarm-bg p-2.5 text-xs text-alarm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span><b>Contradicts your verdicts:</b> this draft changes {fc.violations.map((c, i) => <span key={c}>{i > 0 && ", "}<span className="font-mono">{c}</span></span>)} (a call you marked correct, or a labelled call moving the wrong way).</span>
        </p>
      )}
      {fc && fc.fixed.length > 0 && (
        <p className="mt-4 flex gap-2 rounded-md border border-ok bg-ok-bg p-2.5 text-xs text-ok">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>Fixes {fc.fixed.length} of your flagged verdicts: <span className="font-mono">{fc.fixed.join(", ")}</span>.</span>
        </p>
      )}

      <h3 className="mb-1.5 mt-4 text-sm font-semibold">Calls that would change <span className="font-normal text-muted-foreground">({data.flipped.length})</span></h3>
      {data.flipped.length === 0 ? <p className="text-sm text-muted-foreground">No call would change its decision.</p> : (
        <ul className="space-y-2">{data.flipped.map((f) => (
          <li key={f.call_id} className="rounded-md border border-border p-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              {sampleOnly(f.call_id) ? <span className="font-mono text-xs" title="Sample call: no detail page in fixtures mode">{f.call_id}</span>
                : <Link href={`/calls/${f.call_id}`} className="font-mono text-xs underline underline-offset-2">{f.call_id}</Link>}
              <DecisionBadge decision={f.before} size="sm" />
              {f.direction === "up" ? <ArrowUp className="size-3.5 text-alarm" aria-label="more severe" /> : <ArrowDown className="size-3.5 text-ok" aria-label="less severe" />}
              <DecisionBadge decision={f.after} size="sm" />
              {f.feedback_verdict && <Badge className={f.feedback_verdict === "correct" ? "border-alarm text-alarm" : ""} title="Your verdict on this call">you: {VERDICT_LABEL[f.feedback_verdict].toLowerCase()}</Badge>}
            </div>
            {f.attributed_to.length > 0 && <p className="mt-1 text-[11px] text-muted-foreground">because of {f.attributed_to.map(componentLabel).join(" · ")}</p>}
            {f.reasons.length > 0 && (
              <details className="mt-1 text-xs text-muted-foreground"><summary className="cursor-pointer">why</summary>
                <ul className="mt-1 list-disc space-y-0.5 pl-5">{f.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></details>
            )}
          </li>
        ))}</ul>
      )}
      <p className="mt-3 text-[11px] text-muted-foreground">
        {data.baseline_version === "unknown" ? "This server has no /simulate yet, so these numbers come from /settings/preview: no reasons per call and no check against your verdicts."
          : isFixtures ? "MOCK: a hand-made draft is a client-side approximation over 12 invented sample calls; a suggestion’s Preview shows its real simulated result."
          : `Re-decided from cached transcripts and extractions (${data.n_calls} calls, ${data.n_locked} with stage errors stay in review). Nothing is re-transcribed.`}
      </p>
    </div>
  );
}
