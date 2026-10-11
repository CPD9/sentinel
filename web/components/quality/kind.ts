import type { QualityReport } from "@/lib/types";

/** Tuned-on or unseen, read from the report's own notes ("UNSEEN …", "TUNED ON: …"); the split name alone can mislead
 *  (Testset_30 was cleared by the organisers for tuning, so a "test" report can be tuned-on). */
export function kindOf(r: QualityReport): { unseen: boolean; label: string; prefix: boolean; inSample: boolean } {
  const prefix = r.notes.some((n) => /^PRE-FIX/i.test(n));
  const inSample = r.split === "all" || r.notes.some((n) => /^TUNED ON ALL/i.test(n));
  if (inSample) return { unseen: false, label: `all ${r.overall.n} case calls`, prefix, inSample };
  const note = r.notes.find((n) => /^(UNSEEN|TUNED ON)/i.test(n)) ?? "";
  const unseen = /^UNSEEN/i.test(note) || (!note && r.split === "holdout");
  const label = note ? note.replace(/^(UNSEEN|TUNED ON):?\s*/i, "").split(/[(:,]/)[0].trim() : r.split;
  return { unseen, label: prefix ? `${label}, pre-fix` : label, prefix, inSample };
}

