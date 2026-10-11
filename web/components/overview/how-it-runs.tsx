"use client";
// How it runs: the self-hosted pipeline, where it runs tonight vs. in production, the guarantees, the operating concept,
// and the versions of the run on screen (read from a real result, not typed in).
import Link from "next/link";
import { CopyButton } from "@/components/ui/copy-button";
import { getCall, getCalls } from "@/lib/data";
import { useAsync } from "@/lib/use-async";

const STEPS: { name: string; what: string; kind: "ai" | "rule" | "out" }[] = [
  { name: "Transcribe", what: "Swiss German speech to text with timestamps (Whisper large-v3-turbo, on our own hardware)", kind: "ai" },
  { name: "Who speaks", what: "advisor or customer when known; “unknown” is allowed (the speech run has no speaker separation yet)", kind: "ai" },
  { name: "Keywords", what: "word families with Swiss German variants, fuzzy match", kind: "rule" },
  { name: "AI facts", what: "an open-weight LLM on our own server reads the whole call and lists who did what, with quotes", kind: "ai" },
  { name: "Evidence check", what: "every quote must be found in the transcript, or the fact is dropped", kind: "rule" },
  { name: "Rules", what: "one fixed rule per kind of fraud turns facts into a risk", kind: "rule" },
  { name: "Confidence", what: "transcript clarity, audio quality, contradictions, distance to a line", kind: "rule" },
  { name: "Decision", what: "unsure → review; verified evidence over the line → alert; else no alert", kind: "rule" },
  { name: "Explain + passages", what: "the reason, “why not flagged”, and each passage ±10 s of audio", kind: "out" },
  { name: "Officer", what: "inbox, one-click verdict, report to the trigger API", kind: "out" },
];

export function HowItRuns() {
  const v = useAsync(async () => {
    const calls = await getCalls();
    const first = calls.find((c) => c.status === "done");
    const d = first ? await getCall(first.call_id) : null;
    return d?.kind === "result" ? d.data.versions : null;
  }, "how-versions");

  return (
    <div className="stage-in mx-auto max-w-6xl space-y-10 py-4">
      <div className="space-y-2">
        <Link href="/overview" className="text-sm text-muted-foreground hover:text-foreground">← Overview</Link>
        <h1 className="text-headline font-semibold tracking-tight">How it runs</h1>
        <p className="text-sm"><Link href="/model-card" className="underline underline-offset-4">Model &amp; data card →</Link></p>
        <p className="max-w-3xl text-lead text-muted-foreground">Perceive with AI, decide with rules. The AI steps find what was said; fixed, editable rules decide. Every step runs on servers we control.</p>
      </div>

      <section aria-label="Pipeline" className="space-y-3">
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((s, i) => (
            <li key={s.name} className="elevated stage-in rounded-2xl p-4" style={{ "--i": i } as React.CSSProperties}>
              <p className="flex items-center gap-2 text-xs text-muted-foreground"><span className="tabular">{String(i + 1).padStart(2, "0")}</span>
                <span className={s.kind === "ai" ? "rounded-full bg-info-bg px-2 text-info" : s.kind === "rule" ? "rounded-full bg-muted px-2" : "rounded-full bg-ok-bg px-2 text-ok"}>{s.kind === "ai" ? "AI" : s.kind === "rule" ? "rules" : "output"}</span></p>
              <p className="mt-2 font-semibold">{s.name}</p>
              <p className="mt-1 text-sm text-muted-foreground">{s.what}</p>
            </li>
          ))}
        </ol>
      </section>

      <RunYourCalls />

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
          <h2 className="eyebrow">Where it runs</h2>
          <dl className="space-y-3">
            <div><dt className="font-semibold">Tonight (demo)</dt><dd className="text-sm text-muted-foreground">A rented GPU server running our own open-weight models (Apertus, served with vLLM), reached only through an SSH tunnel. Fictional case data only.</dd></div>
            <div><dt className="font-semibold">Production target</dt><dd className="text-sm text-muted-foreground">The same containers on a Swiss-region server or on the bank&rsquo;s own hardware. Not built yet.</dd></div>
          </dl>
        </div>
        <div className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
          <h2 className="eyebrow">Guarantees</h2>
          <ul className="space-y-1.5 text-sm">
            <li>No cloud AI or speech service: models run on our servers; remote providers are blocked in code for real data.</li>
            <li>Services listen only on the machine itself (127.0.0.1); nothing is exposed to the internet.</li>
            <li>No alert without a verified passage, whatever the settings.</li>
            <li>A failed step is shown and sends the call to review; it is never a silent “no alert”.</li>
            <li>Settings changes are previewed, saved explicitly and logged.</li>
          </ul>
        </div>
      </section>

      <section className="elevated space-y-3 rounded-[var(--radius-panel)] p-6">
        <h2 className="eyebrow">Operating concept</h2>
        <ol className="grid gap-4 text-sm md:grid-cols-4">
          <li><p className="font-semibold">1 · Calls arrive</p><p className="text-muted-foreground">Recorded calls are processed as they come in, every one of them.</p></li>
          <li><p className="font-semibold">2 · Officers work the inbox</p><p className="text-muted-foreground">Alerts first, then reviews; each with its reason and passage.</p></li>
          <li><p className="font-semibold">3 · Verdicts feed back</p><p className="text-muted-foreground">Dismiss, flag, escalate or confirm; confirmed fraud goes to the trigger API.</p></li>
          <li><p className="font-semibold">4 · Tune without code</p><p className="text-muted-foreground">One alert line and keyword families, with the effect shown before saving.</p></li>
        </ol>
      </section>

      <section className="space-y-2">
        <h2 className="eyebrow">The run on screen</h2>
        {v.data ? (
          <dl className="grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
            {[["Speech to text", v.data.asr], ["Language model", v.data.llm?.split("@")[0]], ["Prompt", v.data.prompt], ["Rules", v.data.rules], ["Model server", v.data.provider],
              ["Self-hosted", v.data.self_hosted == null ? null : v.data.self_hosted ? "yes" : "no"]].map(([k, val]) => (
              <div key={k} className="flex gap-3"><dt className="w-36 shrink-0 text-muted-foreground">{k}</dt><dd className="font-mono text-xs leading-5">{val ?? "–"}</dd></div>
            ))}
          </dl>
        ) : <p className="text-sm text-muted-foreground">{v.status === "loading" ? "Loading…" : "No finished call to read versions from."}</p>}
      </section>
    </div>
  );
}

const CMD = "./run.sh /path/to/your_wavs --transcripts asr --out out";
const TREE = `out/
├── results.json            every call: decision, risk, confidence
├── results/<call_id>.json  findings, evidence, reason, versions
├── snippets/<call_id>/     each cited passage ±10 s (.wav)
├── triggers/               trigger API payloads (dry run)
└── id_map.json             file name → neutral call id`;

/** Feasibility: one command over a folder of WAVs, what it writes, how long it took, what it needs. */
function RunYourCalls() {
  return (
    <section aria-labelledby="run-own" className="elevated space-y-5 rounded-[var(--radius-panel)] p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="run-own" className="text-title font-semibold">Run it on your own calls</h2>
        <p className="text-sm text-muted-foreground">No manual steps · no cloud AI · models self-hosted</p>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3">
          <p className="eyebrow">One command, from the repository root</p>
          <div className="flex items-start gap-2 rounded-xl bg-muted p-3">
            <code className="min-w-0 flex-1 break-all font-mono text-sm">{CMD}</code>
            <CopyButton text={CMD} />
          </div>
          <p className="text-sm text-muted-foreground">
            Needs two settings in <code className="font-mono">.env</code>: <code className="font-mono">ASR_MODEL_PATH</code> (the Swiss German Whisper model,
            here <code className="font-mono">faster-whisper-large-v3-turbo</code>) and <code className="font-mono">LLM_BASE_URL</code> (our own model server). Every WAV
            in the folder is transcribed, checked and decided; no API or web app has to run. A step that fails is recorded on the call and sends it to review.
          </p>
          <dl className="grid grid-cols-[minmax(0,12rem)_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">Cold run, fresh folder</dt><dd><b className="tabular">188 s for 2 WAVs</b> (~95 s per call), laptop CPU for speech, from the final evaluation</dd>
            <dt className="text-muted-foreground">One 2 min 23 s call</dt><dd><b className="tabular">56 s</b>, measured tonight: speech on the laptop CPU, facts on our GPU</dd>
            <dt className="text-muted-foreground">Final run</dt><dd>all 62 calls in one command, zero failed steps</dd>
          </dl>
        </div>
        <div className="space-y-3">
          <p className="eyebrow">What it writes</p>
          <pre className="overflow-x-auto whitespace-pre rounded-xl bg-muted p-3 font-mono text-xs leading-relaxed">{TREE}</pre>
          <p className="text-xs text-muted-foreground">Original file names stay in <code className="font-mono">id_map.json</code>; only the neutral id reaches the models.</p>
          <p className="text-xs text-muted-foreground">Models are downloaded once; after that nothing is sent to a cloud service. Speech recognition runs on the machine itself, the language model on our own GPU server through an SSH tunnel.</p>
        </div>
      </div>
    </section>
  );
}
