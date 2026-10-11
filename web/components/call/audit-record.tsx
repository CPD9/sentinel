"use client";
// Audit record: what a compliance officer files for one call. One document, printable to a clean A4 (print CSS in
// globals.css: only .print-area is printed, in light colours). Every line comes from the call's result, decision
// trace and transcript; a field is "not recorded" only when no document carries it.
//   decision + path · fired rules → facts → quote → segment → timestamp → snippet · dropped facts · counter-evidence ·
//   confidence breakdown · run, models, revisions, prompt, rules, thresholds · integrity checks · stage errors
import { Printer } from "lucide-react";
import { CRITERION_LABEL } from "@/lib/colors";
import { getFeedback, getJudge, getRunInfo, snippetUrl } from "@/lib/data";
import { COMPONENT_WORDS, DECISION_LABEL, actLabel, infoLabel, score, speakerLabel } from "@/lib/explain";
import { fmtDateTime, fmtRange } from "@/lib/format";
import type { CallResult, DecisionTrace, Fact, Transcript } from "@/lib/types";
import { useAsync } from "@/lib/use-async";

const PATH_TEXT: Record<string, string> = {
  stage_error: "Step 1: a processing step failed, so the call goes to review",
  missing_evidence: "Step 1: evidence that could change the outcome was not verified, so the call goes to review",
  contradictory_evidence: "Step 1: facts contradict each other on the same passage, so the call goes to review",
  low_confidence: "Step 1: confidence below the gate on a call with some risk, so the call goes to review",
  alarm: "Step 2: a fired rule with verified facts at or above the alert line",
  review_band: "Step 3: risk between the review line and the alert line",
  no_alert: "Step 4: no rule reached the review line",
  judge_alarm: "AI judge: its verdict decides (alert, with at least one cited passage); facts and rules stay as the why",
  judge_review: "AI judge: its verdict decides (review: a person looks); facts and rules stay as the why",
  judge_no_alert: "AI judge: its verdict decides (no violation found); facts and rules stay as the why",
};

/** "apertus-8b@/…/snapshots/a411d83…" → { name: "apertus-8b", rev: "a411d838600b" }. */
function splitVersion(v: string | null | undefined): { name: string; rev: string | null } | null {
  if (!v) return null;
  const [name, rest] = v.split("@");
  if (!rest) return { name, rev: null };
  const snap = /snapshots\/([0-9a-f]{7,})/.exec(rest)?.[1];
  return { name, rev: (snap ?? rest).slice(0, 12) };
}

export function AuditRecord({ result, trace, transcript }: { result: CallResult; trace: DecisionTrace | null; transcript: Transcript | null }) {
  const run = useAsync(getRunInfo, "run-info");
  const fb = useAsync(getFeedback, "feedback");
  const judge = useAsync(() => getJudge(result.call_id), `judge:${result.call_id}`).data ?? null;
  const verdict = fb.data?.find((e) => e.call_id === result.call_id) ?? null;
  const seg = new Map((transcript?.segments ?? []).map((s) => [s.id, s]));
  const facts = new Map((trace?.facts ?? []).map((f) => [f.fact_id, f]));
  const hits = new Map((trace?.keyword_hits ?? []).map((h) => [h.hit_id, h]));
  // snippet per segment id, from the result's evidence (the cut passage ±10 s)
  const snippetOf = new Map<string, string>();
  for (const f of result.findings) for (const e of f.evidence) if (e.snippet_path) for (const id of e.segment_ids) if (!snippetOf.has(id)) snippetOf.set(id, e.snippet_path);
  const ts = (ids: string[]) => {
    const ss = ids.map((id) => seg.get(id)).filter((s): s is NonNullable<typeof s> => !!s && s.start_s != null);
    return ss.length ? fmtRange(Math.min(...ss.map((s) => s.start_s!)), Math.max(...ss.map((s) => s.end_s ?? s.start_s!))) : transcript?.mode === "reference" ? "no timestamp (reference transcript)" : "not recorded";
  };
  const rules = trace ? [...trace.rules].filter((r) => r.fired || r.risk > 0).sort((a, b) => Number(b.fired) - Number(a.fired) || b.risk - a.risk) : [];
  const dropped = trace?.facts.filter((f) => !f.valid) ?? [];
  const countered = trace?.facts.filter((f) => f.valid && f.counter_evidence) ?? [];
  const v = { asr: splitVersion(result.versions.asr), llm: splitVersion(result.versions.llm) };
  const sameDecision = !trace || trace.decision === result.decision;
  const sameVersions = !trace || (["asr", "llm", "prompt", "rules"] as const).every((k) => (trace.versions[k] ?? null) === (result.versions[k] ?? null));

  return (
    <article className="print-area elevated space-y-7 rounded-[var(--radius-panel)] p-6" aria-labelledby="audit-h">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
        <div>
          <p className="eyebrow">Sentinel · audit record</p>
          <h2 id="audit-h" className="text-title font-semibold">Call <span className="font-mono">{result.call_id}</span>: {DECISION_LABEL[result.decision]}</h2>
          <p className="text-sm text-muted-foreground">Generated {fmtDateTime(new Date().toISOString())} from the call&rsquo;s result, decision trace and transcript.</p>
        </div>
        <button type="button" onClick={() => window.print()} className="no-print inline-flex h-10 items-center gap-2 rounded-full border border-foreground/60 px-5 text-sm font-semibold hover:bg-muted">
          <Printer className="size-4" aria-hidden />Print / save as PDF
        </button>
      </header>

      {(!sameDecision || !sameVersions) && (
        <p role="alert" className="rounded-lg border border-alarm/40 bg-alarm-bg px-3 py-2 text-sm text-alarm">
          Integrity check failed: the decision trace {sameDecision ? "" : `says ${DECISION_LABEL[trace!.decision]} while the result says ${DECISION_LABEL[result.decision]}`}
          {!sameDecision && !sameVersions ? " and " : ""}{sameVersions ? "" : "was written with other model or prompt versions than the result"}. The two documents come from different runs; do not file this record.
        </p>
      )}

      <Section title="1 · Decision">
        <Rows rows={[
          ["Decision", DECISION_LABEL[result.decision]],
          ["Decision path", trace ? `${trace.decision_path} — ${PATH_TEXT[trace.decision_path] ?? ""}` : "not recorded (no decision trace)"],
          ["Risk", `${score(result.risk_score)} (alert line ${trace ? score(trace.thresholds.alarm) : "not recorded"}, review line ${trace ? score(trace.thresholds.review) : "not recorded"})`],
          ["Confidence", result.confidence == null ? "not computed" : `${score(result.confidence)} (gate ${trace ? score(trace.thresholds.confidence_gate) : "not recorded"})`],
          ["Officer verdict", verdict ? `${verdict.verdict.replace("_", " ")} · ${fmtDateTime(verdict.ts)}${verdict.note ? ` · “${verdict.note}”` : ""}` : "none recorded"],
        ]} />
      </Section>

      {judge && (
        <Section title="1b · AI judge">
          <Rows rows={[
            ["Verdict", `${DECISION_LABEL[judge.decision]} · ${CRITERION_LABEL[judge.criterion as keyof typeof CRITERION_LABEL] ?? judge.criterion} · risk ${score(judge.risk)}`],
            ["Reason (as written by the judge)", judge.reason],
            ["Judge version", judge.version ?? "not recorded"],
          ]} />
          {judge.citations.length > 0 && (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 pr-3 font-medium">Citation</th><th className="py-1 pr-3 font-medium">Quote</th><th className="py-1 pr-3 font-medium">Segment</th><th className="py-1 pr-3 font-medium">Time</th><th className="py-1 font-medium">Snippet</th></tr></thead>
              <tbody className="divide-y divide-border align-top">
                {judge.citations.map((c) => {
                  const sn = c.segment_ids.map((x) => snippetOf.get(x)).find(Boolean) ?? null;
                  const url = sn ? snippetUrl(result.call_id, sn) : null;
                  return (
                    <tr key={c.fact_id}>
                      <td className="py-1.5 pr-3 font-mono text-xs">{c.fact_id}{!c.valid && " (not grounded)"}</td>
                      <td className="py-1.5 pr-3" lang="de">“{c.quote}”</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{c.segment_ids.join(", ")}</td>
                      <td className="tabular py-1.5 pr-3 text-xs">{ts(c.segment_ids)}</td>
                      <td className="py-1.5 font-mono text-xs">{sn ? (url ? <a href={url} className="underline underline-offset-2">{sn.split("/").pop()}</a> : sn.split("/").pop()) : "not cut"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Section>
      )}

      <Section title="2 · Rules, facts and evidence">
        {!trace ? <p className="text-sm text-muted-foreground">No decision trace for this call, so the rule inputs are not recorded.</p>
          : rules.length === 0 ? <p className="text-sm">No rule fired and no rule scored above zero.</p> : rules.map((r) => (
            <div key={r.criterion} className="audit-block space-y-2">
              <p className="font-semibold">{CRITERION_LABEL[r.criterion] ?? r.criterion} · {r.fired ? "fired" : "did not fire"} · risk {score(r.risk)}</p>
              <p className="font-mono text-xs text-muted-foreground">{r.reason}</p>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th className="py-1 pr-3 font-medium">Fact</th><th className="py-1 pr-3 font-medium">Who / what</th><th className="py-1 pr-3 font-medium">Quote (gloss)</th><th className="py-1 pr-3 font-medium">Segment</th><th className="py-1 pr-3 font-medium">Time</th><th className="py-1 font-medium">Snippet</th></tr>
                </thead>
                <tbody className="divide-y divide-border align-top">
                  {r.fact_ids.map((id) => facts.get(id)).filter((f): f is Fact => !!f).map((f) => {
                    const sn = f.segment_ids.map((s) => snippetOf.get(s)).find(Boolean) ?? null;
                    const url = sn ? snippetUrl(result.call_id, sn) : null;
                    return (
                      <tr key={f.fact_id}>
                        <td className="py-1.5 pr-3 font-mono text-xs">{f.fact_id}{!f.valid && " (dropped)"}</td>
                        <td className="py-1.5 pr-3">{speakerLabel(f.speaker)} {actLabel(f.act)} {infoLabel(f.info_type)}{f.recipient_third_party ? ", to a third party" : ""}{f.secrecy_cue ? ", secrecy cue" : ""}</td>
                        <td className="py-1.5 pr-3"><span lang="gsw">“{f.quote}”</span>{f.gloss_de && <span lang="de" className="block text-muted-foreground">“{f.gloss_de}”</span>}</td>
                        <td className="py-1.5 pr-3 font-mono text-xs">{f.segment_ids.join(", ")}</td>
                        <td className="tabular py-1.5 pr-3 text-xs">{ts(f.segment_ids)}</td>
                        <td className="py-1.5 font-mono text-xs">{sn ? (url ? <a href={url} className="underline underline-offset-2">{sn.split("/").pop()}</a> : sn.split("/").pop()) : transcript?.mode === "reference" ? "none (no timestamps)" : "not cut"}</td>
                      </tr>
                    );
                  })}
                  {r.keyword_hit_ids.map((id) => hits.get(id)).filter(Boolean).map((h) => (
                    <tr key={h!.hit_id}>
                      <td className="py-1.5 pr-3 font-mono text-xs">{h!.hit_id}</td>
                      <td className="py-1.5 pr-3">keyword ({h!.family})</td>
                      <td className="py-1.5 pr-3"><span lang="gsw">“{h!.matched_text}”</span> <span className="text-muted-foreground">for “{h!.term}”, score {h!.score.toFixed(2)}</span></td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{h!.segment_id}</td>
                      <td className="tabular py-1.5 pr-3 text-xs">{ts([h!.segment_id])}</td>
                      <td className="py-1.5 font-mono text-xs">{snippetOf.get(h!.segment_id)?.split("/").pop() ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
      </Section>

      <Section title="3 · Dropped facts and counter-evidence">
        {!trace ? <p className="text-sm text-muted-foreground">No decision trace.</p> : (
          <div className="space-y-2 text-sm">
            {dropped.length === 0 ? <p>No fact was dropped by the evidence check.</p> : (
              <ul className="space-y-1">{dropped.map((f) => <li key={f.fact_id}><span className="font-mono text-xs">{f.fact_id}</span> <span lang="gsw">“{f.quote}”</span> — dropped: {f.drop_reason ?? "reason not recorded"}</li>)}</ul>
            )}
            {countered.length === 0 ? <p>No fact carries counter-evidence.</p> : (
              <ul className="space-y-1">{countered.map((f) => <li key={f.fact_id}><span className="font-mono text-xs">{f.fact_id}</span> counter-evidence: {f.counter_evidence}</li>)}</ul>
            )}
          </div>
        )}
      </Section>

      <Section title="4 · Confidence breakdown">
        {!trace?.confidence_breakdown ? <p className="text-sm">Confidence was not computed for this call.</p> : (
          <Rows rows={[
            ...Object.entries(trace.confidence_breakdown.components).map(([k, val]) => [COMPONENT_WORDS[k]?.label ?? k, `${score(val)} · ${val < 0.7 ? COMPONENT_WORDS[k]?.low ?? "concern" : COMPONENT_WORDS[k]?.ok ?? "no concern"}`] as [string, string]),
            ["Total", `${score(trace.confidence_breakdown.value)} vs gate ${score(trace.confidence_breakdown.gate)}`],
          ]} />
        )}
      </Section>

      <Section title="5 · Run, models and settings">
        <Rows rows={[
          ["Run", run.data ? `${run.data.run_id} (${run.data.mode} transcripts, created ${fmtDateTime(run.data.created_at)})` : "run id not provided by this server"],
          ["Language model", v.llm ? `${v.llm.name}${v.llm.rev ? ` · revision ${v.llm.rev}` : ""}` : "not recorded"],
          ["Speech recognition", v.asr ? `${v.asr.name}${v.asr.rev ? ` · revision ${v.asr.rev}` : ""}` : "not recorded"],
          ["Prompt version", result.versions.prompt ?? "not recorded"],
          ["Rules version", result.versions.rules ?? "not recorded"],
          ["Model server", `${result.versions.provider ?? "not recorded"}${result.versions.self_hosted == null ? "" : result.versions.self_hosted ? " · self-hosted" : " · NOT self-hosted"}`],
          ["Thresholds", trace ? `alert ${trace.thresholds.alarm.toFixed(2)} · review ${trace.thresholds.review.toFixed(2)} · confidence gate ${trace.thresholds.confidence_gate.toFixed(2)}` : "not recorded"],
          ["Integrity", `result and trace ${sameDecision ? "agree on the decision" : "DISAGREE on the decision"}; versions ${sameVersions ? "match" : "DIFFER"}`],
          ["Stage errors", result.stage_errors.length ? result.stage_errors.map((e) => `${e.stage}: ${e.message}`).join(" · ") : "none"],
        ]} />
      </Section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="audit-block space-y-2"><h3 className="eyebrow">{title}</h3>{children}</section>;
}
function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[12rem_minmax(0,1fr)]">
      {rows.map(([k, val]) => <div key={k} className="contents"><dt className="text-muted-foreground">{k}</dt><dd className="break-words">{val}</dd></div>)}
    </dl>
  );
}
