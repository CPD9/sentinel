"use client";
import { Badge } from "@/components/ui/badge";
import type { ArenaLeaderboard } from "@/lib/data-arena";

const f2 = (x: number | null | undefined) => (x == null ? "n/a" : x.toFixed(2));
const pct = (x: number | null | undefined) => (x == null ? "n/a" : `${Math.round(x * 100)}%`);
const secs = (ms: number | null) => (ms == null ? "n/a" : `${(ms / 1000).toFixed(1)} s`);

/** AUC point + CI on a 0–1 axis with the 0.5 chance line. */
function AucBar({ v, lo, hi }: { v: number | null; lo: number | null; hi: number | null }) {
  return (
    <div className="relative h-3 w-28" role="img" aria-label={v == null ? "AUC undefined" : `AUC ${v.toFixed(2)}, CI ${f2(lo)} to ${f2(hi)}`}>
      <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
      <div className="absolute top-0 h-3 w-px bg-muted-foreground/60" style={{ left: "50%" }} title="chance (0.5)" />
      {lo != null && hi != null && <div className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-foreground/60" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />}
      {v != null && <div className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground" style={{ left: `${v * 100}%` }} />}
    </div>
  );
}

export function Leaderboard({ data }: { data: ArenaLeaderboard }) {
  const rows = data.rows;
  return (
    <div className="space-y-3">
      <div className="elevated overflow-x-auto rounded-2xl">
        <table className="w-full min-w-[900px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-2 py-3 font-medium">Model</th>
              <th className="px-2 py-3 font-medium">AUC [95% CI]</th>
              <th className="px-2 py-3 text-right font-medium">False alarms</th>
              <th className="px-2 py-3 text-right font-medium">Missed</th>
              <th className="px-2 py-3 text-right font-medium">Balanced acc.</th>
              <th className="px-2 py-3 text-right font-medium">Citations valid</th>
              <th className="px-2 py-3 text-right font-medium">Latency p50 / p90</th>
              <th className="px-2 py-3 text-right font-medium">Cost (62 calls)</th>
              <th className="px-4 py-3 text-right font-medium">Errors</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.slug} className="border-b border-border/60 last:border-0">
                <td className="tabular px-4 py-3 text-muted-foreground">{i + 1}</td>
                <td className="px-2 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{r.model}</span>
                    {r.self_hosted
                      ? <Badge className="border-transparent" style={{ background: "var(--ok-bg)", color: "var(--ok)" }}>self-hosted · production</Badge>
                      : <Badge className="text-muted-foreground">OpenRouter · fictional case data only</Badge>}
                  </div>
                </td>
                <td className="px-2 py-3">
                  <div className="flex items-center gap-3">
                    <AucBar v={r.auc} lo={r.auc_ci95[0]} hi={r.auc_ci95[1]} />
                    <span className="tabular whitespace-nowrap"><b>{f2(r.auc)}</b> <span className="text-xs text-muted-foreground">[{f2(r.auc_ci95[0])}, {f2(r.auc_ci95[1])}]</span></span>
                  </div>
                </td>
                <td className="tabular whitespace-nowrap px-2 py-3 text-right">{r.false_alarms}<span className="text-xs text-muted-foreground"> / {r.false_alarms + r.tn}</span></td>
                <td className="tabular whitespace-nowrap px-2 py-3 text-right">{r.missed}<span className="text-xs text-muted-foreground"> / {r.n_positive}</span></td>
                <td className="tabular whitespace-nowrap px-2 py-3 text-right">{f2(r.balanced_accuracy)}</td>
                <td className="tabular whitespace-nowrap px-2 py-3 text-right">{pct(r.citation_validity)}<span className="text-xs text-muted-foreground"> ({r.citations_valid}/{r.citations_total})</span></td>
                <td className="tabular px-2 py-3 text-right whitespace-nowrap">{secs(r.latency_ms_median)} / {secs(r.latency_ms_p90)}</td>
                <td className="tabular px-2 py-3 text-right whitespace-nowrap">{r.self_hosted ? <span className="text-xs text-muted-foreground">GPU time</span> : r.cost_usd == null ? "n/a" : `$${r.cost_usd.toFixed(3)}`}</td>
                <td className="tabular px-4 py-3 text-right" title={r.error_calls.join(", ")}>{r.errors}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="max-w-4xl text-xs text-muted-foreground">
        Same S4 judge prompt (<code>{data.prompt_version}</code>) on the speech-recognition transcripts of all {data.n_calls} case calls (fictional),
        temperature 0, strict JSON, same citation validator as production. AUC: ranking of each model&apos;s risk vs the gold escalation
        (alarm or review vs no alert), 95% CI from resampling whole dialogues. False alarms, missed and balanced accuracy use each
        model&apos;s own decision; nothing is tuned. A failed call counts as a miss. n is small: overlapping CIs are not a measured win.
      </p>
      <p className="max-w-4xl text-xs text-muted-foreground">
        Known failures (first pass, not retried): call_030 fails on every remote model because its transcript line holds a long
        repeated card number and the models copy it into the quote until the 700-token limit. qwen3-32b&apos;s thinking intermittently
        exhausts the same 700-token budget (12 calls). Remote scores are for OpenRouter-hosted weights; a swap means serving the
        same weights ourselves and re-measuring.
      </p>
    </div>
  );
}
