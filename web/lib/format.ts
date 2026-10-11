/** mm:ss, or one decimal for windows shorter than 10 s (PRODUCT.md conventions). */
export function fmtTime(s: number | null | undefined, decimals = false): string {
  if (s == null || !isFinite(s)) return "–";
  const total = decimals ? Math.round(s * 10) / 10 : Math.floor(s); // round first so 59.96 → 01:00.0, not 00:60.0
  const m = Math.floor(total / 60);
  const sec = total - m * 60;
  const secStr = decimals ? sec.toFixed(1).padStart(4, "0") : sec.toString().padStart(2, "0");
  return `${m.toString().padStart(2, "0")}:${secStr}`;
}

export function fmtRange(start: number | null, end: number | null): string {
  if (start == null || end == null) return "no timestamp";
  const short = end - start < 10;
  return `${fmtTime(start, short)}–${fmtTime(end, short)}`;
}

/** 0–1 score as 0–100 %. null → "n/a". */
export function pct(x: number | null | undefined, digits = 0): string {
  return x == null ? "n/a" : `${(x * 100).toFixed(digits)} %`;
}

export function fmtMetric(x: number | null | undefined, digits = 2): string {
  return x == null ? "n/a (undefined)" : x.toFixed(digits);
}

export function fmtSeconds(x: number | null | undefined): string {
  if (x == null) return "–";
  return x < 0.0005 ? "<1 ms" : x < 1 ? `${(x * 1000).toFixed(0)} ms` : `${x.toFixed(1)} s`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

export function humanize(s: string): string {
  return s.replaceAll("_", " ");
}

export const VERDICT_LABEL = { false_alarm: "False alarm", missed: "Missed", correct: "Correct", escalate: "Escalated" } as const;

/** "thresholds.alarm=0.8" → "alert line 0.8", "rules.disable:insider_trading" → "rule insider trading off". */
export function componentLabel(c: string): string {
  const [kind, rest = ""] = c.split(/[=:]/);
  if (kind === "thresholds.confidence_gate") return `confidence gate ${rest}`;
  if (kind.startsWith("thresholds.")) return `${kind.slice(11)} threshold ${rest}`;
  if (kind === "keywords.disable") return `keyword family ${rest} off`;
  if (kind === "rules.disable") return `rule ${humanize(rest)} off`;
  return humanize(c);
}
