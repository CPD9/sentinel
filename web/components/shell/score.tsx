import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Horizontal 0–1 bar with optional threshold markers. */
export function ScoreBar({
  value, color = "var(--foreground)", markers = [], className, label,
}: {
  value: number | null; color?: string; className?: string; label?: string;
  markers?: { at: number; label: string }[];
}) {
  const v = value == null ? 0 : Math.min(1, Math.max(0, value));
  return (
    <div className={cn("relative h-2 w-full rounded-full bg-muted", className)} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={value ?? undefined}>
      <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${v * 100}%`, background: color }} />
      {markers.map((m) => (
        <div key={m.label} className="absolute -top-1 h-4 w-px bg-foreground/70" style={{ left: `${m.at * 100}%` }} title={`${m.label} ${pct(m.at)}`} />
      ))}
    </div>
  );
}

/** Risk and confidence are always shown together (PRODUCT.md). Confidence dims below the gate. */
export function RiskConfidence({ risk, confidence, gate, compact }: { risk: number | null; confidence: number | null; gate?: number; compact?: boolean }) {
  const dim = confidence != null && gate != null && confidence < gate;
  return (
    <div className={cn("flex items-center gap-3 tabular text-sm", compact && "text-xs")}>
      <span title="risk"><span className="text-muted-foreground">risk </span><b>{pct(risk)}</b></span>
      <span title={dim ? "confidence below the gate" : "confidence"} className={cn(dim && "text-review")}>
        <span className="text-muted-foreground">conf </span><b>{pct(confidence)}</b>{dim && " ▼"}
      </span>
    </div>
  );
}
