"use client";
// Model & data card: what runs where, under which licence, on which data, what was tuned and what is unseen, and what
// does not work yet. Detection numbers are read from the quality reports on screen; the rest is from docs/RESULTS.md
// (final system, 11 Oct 2026) and artifacts/metrics (ASR benchmark). Nothing here is a placeholder.
import Link from "next/link";
import { kindOf } from "@/components/quality/kind";
import { getQualityReport, getQualityReports } from "@/lib/data";
import { useAsync } from "@/lib/use-async";

const MODELS = [
  { role: "Speech to text", name: "Whisper large-v3-turbo (faster-whisper conversion, mobiuslabsgmbh, revision 0a363e9161cb)", licence: "MIT (OpenAI Whisper weights)", where: "our own hardware: the rented GPU for the final run, a laptop CPU for single calls" },
  { role: "Fact extraction", name: "Apertus v1.5 8B (Swiss AI Initiative), prompt v2, temperature 0", licence: "Apache 2.0, open weights", where: "our vLLM server on a rented NVIDIA A40 (Runpod), reached only through an SSH tunnel" },
  { role: "Compared, not shipped", name: "Qwen2.5-32B-Instruct-AWQ (same server); Llama 3.3 70B (one comparison run)", licence: "open weights", where: "Qwen on our server; the Llama run went through OpenRouter on fictional case transcripts only, which the provider gate allows for open-weight models" },
];

export function ModelCard() {
  const reports = useAsync(async () => Promise.all((await getQualityReports()).map((x) => getQualityReport(x.report_id))), "q-all");
  const rows = [...(reports.data ?? [])].sort((a, b) => Number(kindOf(a).unseen) - Number(kindOf(b).unseen));
  const p = (v: number | null) => (v == null ? "n/a" : v.toFixed(2));

  return (
    <div className="stage-in mx-auto max-w-6xl space-y-8 py-4">
      <div className="space-y-2">
        <Link href="/how-it-runs" className="text-sm text-muted-foreground hover:text-foreground">← How it runs</Link>
        <h1 className="text-headline font-semibold tracking-tight">Model &amp; data card</h1>
        <p className="max-w-3xl text-lead text-muted-foreground">Which models decide, where they run, which data they saw, and what does not work yet.</p>
      </div>

      <section className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
        <h2 className="eyebrow">Models</h2>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1.5 pr-4 font-medium">Role</th><th className="py-1.5 pr-4 font-medium">Model</th><th className="py-1.5 pr-4 font-medium">Licence</th><th className="py-1.5 font-medium">Where it runs</th></tr></thead>
          <tbody className="divide-y divide-border align-top">
            {MODELS.map((m) => <tr key={m.role}><td className="py-2 pr-4 font-semibold">{m.role}</td><td className="py-2 pr-4">{m.name}</td><td className="py-2 pr-4">{m.licence}</td><td className="py-2 text-muted-foreground">{m.where}</td></tr>)}
          </tbody>
        </table>
        <ul className="space-y-1 text-sm">
          <li><b>No closed models.</b> Every model that touches a call has open weights; the decision itself is made by fixed rules (rules-v2), not by a model.</li>
          <li><b>No call data leaves our infrastructure</b> in the shipped system. Tonight&rsquo;s case data is fictional; the target for real calls is a Swiss-region server or the bank&rsquo;s own hardware (not built yet).</li>
        </ul>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
          <h2 className="eyebrow">Data and splits</h2>
          <ul className="space-y-1.5 text-sm">
            <li><b>62 fictional bank calls</b> from the case (Swiss German, clean and noisy recordings of the same scripts).</li>
            <li>Split by dialogue group: the clean and noisy versions of one script never sit in different splits.</li>
            <li><b>Tuned on:</b> dev (28 calls) and Testset_30 (20 calls, cleared by the organisers for tuning). Prompt, rules and thresholds were chosen there.</li>
            <li><b>Unseen:</b> holdout (14 calls, 7 dialogues), run exactly once with the frozen settings, never used for any choice.</li>
            <li>Labels are read only by the evaluation step, after predictions exist; the pipeline sees neutral call ids, never file names.</li>
          </ul>
        </div>
        <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
          <h2 className="eyebrow">Detection on each split (escalation: alert + review vs no alert)</h2>
          {rows.length === 0 ? <p className="text-sm text-muted-foreground">{reports.status === "loading" ? "Loading the reports…" : "No quality report in this run."}</p> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1 pr-3 font-medium">Split</th><th className="py-1 pr-3 font-medium">n</th><th className="py-1 pr-3 font-medium">Precision</th><th className="py-1 pr-3 font-medium">Recall</th><th className="py-1 font-medium">F1 [95% range]</th></tr></thead>
              <tbody className="tabular divide-y divide-border">
                {rows.map((r) => { const e = r.overall.escalation, k = kindOf(r); return (
                  <tr key={r.report_id} className={k.unseen ? "font-semibold" : ""}>
                    <td className="py-1.5 pr-3">{k.unseen ? "Unseen" : "Tuned on"} · {k.label}</td><td className="py-1.5 pr-3">{r.overall.n}</td>
                    <td className="py-1.5 pr-3">{p(e.precision.value)}</td><td className="py-1.5 pr-3">{p(e.recall.value)}</td>
                    <td className="py-1.5">{p(e.f1.value)}{e.f1.ci_low != null ? ` [${p(e.f1.ci_low)}, ${p(e.f1.ci_high)}]` : ""}</td>
                  </tr>); })}
              </tbody>
            </table>
          )}
          <p className="text-xs text-muted-foreground">From the quality reports of the run on screen ({rows[0]?.run_id ?? "–"}). On the same tuning calls, reference transcripts reach escalation F1 0.63: the gap is the speech step.</p>
        </div>
      </section>

      <section className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
        <h2 className="eyebrow">Known limits</h2>
        <ul className="grid gap-3 text-sm md:grid-cols-2">
          <li><b>Misses on unseen calls.</b> On the 14 unseen calls the system flagged none of the 6 that needed a person, and sent 5 of 8 harmless calls to review. It raised no false alert on any split.</li>
          <li><b>No speaker separation in speech recognition.</b> Every segment is &ldquo;unknown&rdquo;; the model infers who speaks from the content. Speaker diarization is the next step (not built).</li>
          <li><b>Swiss German word error rate 0.63</b> against the Swiss German reference transcripts (3 case calls, clean and noisy alike): Whisper merges turns and moves dialect towards Standard German, so far fewer facts are found (77 on 48 calls vs 673 with reference transcripts).</li>
          <li><b>Small samples.</b> 14 unseen calls (7 dialogues): every number has a wide range; read the ranges, not the point values.</li>
          <li><b>Explanations are templates</b> in this run (no LLM narrative); reasons come from the rules and facts.</li>
          <li><b>Tonight&rsquo;s hardware is rented</b> (A40 on Runpod) and used with fictional data only; the Swiss-region or on-prem deployment is not built.</li>
        </ul>
      </section>
    </div>
  );
}
