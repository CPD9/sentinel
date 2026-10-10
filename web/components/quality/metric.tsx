import { fmtMetric } from "@/lib/format";
import type { Metric } from "@/lib/types";

/** Point estimate with its bootstrap CI as an error bar on a 0–1 axis. null → "n/a (undefined)", never 0. */
export function MetricBar({ label, m }: { label: string; m: Metric }) {
  const has = m.value != null;
  const pctPos = (v: number) => `${v * 100}%`;
  return (
    <div className="grid grid-cols-[6.5rem_1fr] items-center gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <div>
        <div className="flex items-baseline gap-2">
          <b className="tabular">{fmtMetric(m.value)}</b>
          <span className="tabular text-xs text-muted-foreground">{has ? (m.ci_low != null ? `CI ${m.ci_low.toFixed(2)}–${m.ci_high!.toFixed(2)}` : "no CI") : ""}</span>
        </div>
        <div className="relative mt-1 h-3" role="img" aria-label={has ? `${label} ${m.value!.toFixed(2)}${m.ci_low != null ? `, CI ${m.ci_low.toFixed(2)} to ${m.ci_high!.toFixed(2)}` : ""}` : `${label} undefined`}>
          <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
          {[0, 0.5, 1].map((t) => <div key={t} className="absolute top-0 h-3 w-px bg-border" style={{ left: pctPos(t) }} />)}
          {has && m.ci_low != null && (
            <>
              <div className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-foreground/70" style={{ left: pctPos(m.ci_low), width: pctPos(m.ci_high! - m.ci_low) }} />
              <div className="absolute top-0.5 h-2 w-0.5 bg-foreground/70" style={{ left: pctPos(m.ci_low) }} />
              <div className="absolute top-0.5 h-2 w-0.5 bg-foreground/70" style={{ left: pctPos(m.ci_high!) }} />
            </>
          )}
          {has && <div className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-foreground" style={{ left: pctPos(m.value!) }} />}
        </div>
      </div>
    </div>
  );
}
