"use client";
import { Download } from "lucide-react";
import { Fragment, useState } from "react";
import { DocGate, ErrorCard } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtSeconds, humanize, pct } from "@/lib/format";
import type { AnalysisArtifact, CallResult, DecisionTrace, Transcript } from "@/lib/types";
import type { Loadable } from "@/lib/use-async";

const nz = (v: string | null | undefined) => v ?? <span className="text-muted-foreground">not run</span>;

export function AuditTab({ result, trace, analysis, transcript }: {
  result: CallResult; trace: Loadable<DecisionTrace>; analysis: Loadable<AnalysisArtifact>; transcript: Loadable<Transcript>;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Versions</CardTitle></CardHeader>
        <CardContent>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">ASR model</dt><dd className="font-mono">{nz(result.versions.asr)}</dd>
            <dt className="text-muted-foreground">LLM</dt><dd className="font-mono">{nz(result.versions.llm)}</dd>
            <dt className="text-muted-foreground">Prompt</dt><dd className="font-mono">{nz(result.versions.prompt)}</dd>
            <dt className="text-muted-foreground">Rules</dt><dd className="font-mono">{nz(result.versions.rules)}</dd>
            <dt className="text-muted-foreground">Analysis</dt><dd className="font-mono">{analysis.data ? nz(analysis.data.versions.analysis) : <span className="text-muted-foreground">not run</span>}</dd>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Thresholds used for this decision</CardTitle></CardHeader>
        <CardContent>
          <DocGate state={trace} unavailable="No decision trace, so the thresholds are unknown." rows={3}>
            {(t) => (
              <dl className="grid grid-cols-[10rem_1fr] gap-y-1.5 text-sm">
                {Object.entries(t.thresholds).map(([k, v]) => (<Fragment key={k}><dt className="text-muted-foreground">{humanize(k)}</dt><dd className="tabular font-mono">{v.toFixed(2)} ({pct(v)})</dd></Fragment>))}
              </dl>
            )}
          </DocGate>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Per-stage timings</CardTitle></CardHeader>
        <CardContent>
          <DocGate state={trace} unavailable="No decision trace, so there are no timings." rows={3}>
            {(t) => {
              const entries = Object.entries(t.timings_s);
              const max = Math.max(...entries.map(([, v]) => v), 0.001);
              return (
                <ul className="space-y-1.5">
                  {entries.map(([k, v]) => (
                    <li key={k} className="grid grid-cols-[6rem_1fr_4.5rem] items-center gap-2 text-sm">
                      <span className="font-mono text-xs">{k}</span>
                      <div className="h-2 rounded-full bg-muted"><div className="h-2 rounded-full bg-foreground/70" style={{ width: `${Math.max(1, (v / max) * 100)}%` }} /></div>
                      <span className="tabular text-right text-xs">{fmtSeconds(v)}</span>
                    </li>
                  ))}
                </ul>
              );
            }}
          </DocGate>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Stage errors</CardTitle></CardHeader>
        <CardContent>
          {result.stage_errors.length === 0 ? <p className="text-sm text-muted-foreground">None in the call result.</p> : (
            <ul className="space-y-2 text-sm">{result.stage_errors.map((e, i) => <li key={i} className="rounded border border-alarm/50 bg-alarm-bg p-2 text-alarm"><b className="font-mono">{e.stage}</b>: {e.message}</li>)}</ul>
          )}
          {analysis.data && analysis.data.stage_errors.length > 0 && (
            <>
              <h4 className="mb-1 mt-3 text-xs font-semibold text-muted-foreground">Audio analysis (does not affect the decision)</h4>
              <ul className="space-y-1 text-sm">{analysis.data.stage_errors.map((e, i) => <li key={i}><b className="font-mono">{e.stage}</b>: {e.message}</li>)}</ul>
            </>
          )}
        </CardContent>
      </Card>

      <div className="space-y-3 lg:col-span-2">
        <h2 className="text-sm font-semibold">Raw documents</h2>
        <RawDoc name="result" doc={result} file={`${result.call_id}.result.json`} />
        <RawLoadable name="trace" state={trace} file={`${result.call_id}.trace.json`} />
        <RawLoadable name="transcript" state={transcript} file={`${result.call_id}.transcript.json`} />
        <RawLoadable name="analysis" state={analysis} file={`${result.call_id}.analysis.json`} />
      </div>
    </div>
  );
}

/** One failed document never blanks the others. */
function RawLoadable({ name, state, file }: { name: string; state: Loadable<unknown>; file: string }) {
  if (state.data) return <RawDoc name={name} doc={state.data} file={file} />;
  if (state.status === "loading") return <div className="skeleton h-10" aria-busy="true" />;
  if (state.status === "error" && state.error.status !== 404) return <ErrorCard error={state.error} title={`${name} failed to load`} onRetry={state.reload} />;
  return <Card className="p-3 text-sm text-muted-foreground"><b>{name}</b>: not available for this call.</Card>;
}

function RawDoc({ name, doc, file }: { name: string; doc: unknown; file: string }) {
  const [open, setOpen] = useState(false);
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: file });
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Card>
      <div className="flex items-center justify-between gap-2 px-4 py-2">
        <button type="button" className="text-left text-sm font-medium" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "▾" : "▸"} {name} <span className="font-mono text-xs text-muted-foreground">{file}</span></button>
        <Button variant="outline" size="sm" onClick={download}><Download className="size-3.5" />Download</Button>
      </div>
      {open && <pre className="max-h-96 overflow-auto border-t border-border bg-muted p-3 font-mono text-xs">{JSON.stringify(doc, null, 2)}</pre>}
    </Card>
  );
}
