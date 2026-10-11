"use client";
import { Plus, Save, X } from "lucide-react";
import { Fragment, useState } from "react";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CRITERION_LABEL, criterionColor } from "@/lib/colors";
import { ApiError, getKeywords, getRules, putKeywords, putRules } from "@/lib/data";
import type { KeywordsConfig, RulesConfig } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { usePreview } from "@/lib/use-preview";

type Msg = { ok: boolean; text: string } | null;
const fail = (e: unknown): Msg => ({ ok: false, text: e instanceof ApiError ? (Array.isArray(e.detail) ? e.detail.join("; ") : `${e.code}: ${e.detail}`) : String(e) });
const MsgBox = ({ m }: { m: Msg }) => m && <p role={m.ok ? "status" : "alert"} className={`rounded-md border p-3 text-sm ${m.ok ? "border-ok bg-ok-bg text-ok" : "border-alarm bg-alarm-bg text-alarm"}`}>{m.text}</p>;

export function Configuration() {
  return (
    <div className="space-y-8">
      <Keywords />
      <Rules />
    </div>
  );
}

function Keywords() {
  const saved = useAsync(getKeywords, "keywords");
  const [edited, setDraft] = useState<KeywordsConfig | null>(null);
  const draft = edited ?? saved.data;
  const [msg, setMsg] = useState<Msg>(null);
  const preview = usePreview(draft ? { keywords: draft } : null);

  if (saved.status === "error" && !saved.data) return <ErrorCard error={saved.error} onRetry={saved.reload} />;
  if (!draft) return <SkeletonBlock rows={5} />;
  const dirty = edited !== null && JSON.stringify(edited) !== JSON.stringify(saved.data);
  const count = (family: string, term: string) => preview.data?.keyword_hit_counts[family]?.[term];
  const mutate = (fn: (d: KeywordsConfig) => void) => { setMsg(null); setDraft((prev) => { const n = structuredClone(prev ?? saved.data!); fn(n); return n; }); };

  return (
    <section aria-labelledby="kw" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 id="kw" className="text-lg font-semibold">Keywords</h2>
          <p className="max-w-prose text-sm text-muted-foreground">The words the system listens for, grouped by kind of fraud, each with its Swiss German variants. The number next to a word is how many transcript passages match it across all processed calls, live while you edit. Keywords only point to passages; they are never shown to the language model.</p></div>
        <div className="flex gap-2">
          <Button size="sm" disabled={!dirty} onClick={async () => { try { const r = await putKeywords(draft); setMsg({ ok: true, text: `Saved. Re-running keywords, rules, confidence, decide for ${r.rerun.n_calls} calls.` }); setDraft(null); saved.reload(); } catch (e) { setMsg(fail(e)); } }}><Save className="size-4" />Save keywords</Button>
          <Button size="sm" variant="outline" disabled={!dirty} onClick={() => setDraft(null)}>Reset</Button>
        </div>
      </div>
      <MsgBox m={msg} />
      {preview.error && <p className="text-xs text-muted-foreground">Live counts unavailable — {preview.error}</p>}
      <div className="space-y-1">
        <label className="flex flex-wrap items-center gap-3 text-sm font-medium">Match strictness
          <input type="range" min={0.5} max={1} step={0.01} value={draft.fuzzy_threshold} onChange={(e) => mutate((d) => { d.fuzzy_threshold = +e.target.value; })} />
          <span className="tabular font-semibold">{draft.fuzzy_threshold.toFixed(2)}</span>
        </label>
        <p className="text-xs text-muted-foreground">How exactly a transcribed word must match a keyword to count. 1.00 = exact spelling only; lower values also catch dialect spellings and small transcription errors.</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {Object.entries(draft.families).map(([name, f]) => (
          <Card key={name}>
            <CardHeader><div>
              <CardTitle className="flex items-center gap-2 text-base"><span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: criterionColor(f.criterion) }} />{CRITERION_LABEL[f.criterion] ?? f.criterion}</CardTitle>
              <CardDescription>family <span className="font-mono">{name}</span> · words and their Swiss German variants</CardDescription>
            </div></CardHeader>
            <CardContent className="space-y-3">
              <ul className="space-y-2">
                {f.terms.map((term) => (
                  <li key={term} className="rounded-md border border-border p-2">
                    <div className="flex items-center gap-2">
                      <span lang="gsw" className="font-medium">{term}</span>
                      <span className="tabular rounded bg-muted px-1.5 text-xs" title="matching segments across processed calls">{count(name, term) ?? "…"} hits</span>
                      <button className="ml-auto text-muted-foreground hover:text-alarm" aria-label={`Remove term ${term}`} onClick={() => mutate((d) => { const fam = d.families[name]; fam.terms = fam.terms.filter((x) => x !== term); delete fam.variants[term]; })}><X className="size-4" /></button>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      {(f.variants[term] ?? []).map((v) => (
                        <span key={v} className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-xs"><span lang="gsw">{v}</span>
                          <span className="tabular text-muted-foreground">{count(name, v) ?? "…"}</span>
                          <button aria-label={`Remove variant ${v}`} onClick={() => mutate((d) => { d.families[name].variants[term] = d.families[name].variants[term].filter((x) => x !== v); })}><X className="size-3" /></button></span>
                      ))}
                      <AddInput label={`Add variant of ${term}`} placeholder="+ variant" onAdd={(v) => mutate((d) => { const vs = (d.families[name].variants[term] ??= []); if (!vs.includes(v)) vs.push(v); })} />
                    </div>
                  </li>
                ))}
              </ul>
              <AddInput label={`Add term to ${name}`} placeholder="+ word" onAdd={(v) => mutate((d) => { if (!d.families[name].terms.includes(v)) d.families[name].terms.push(v); })} />
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

function AddInput({ label, placeholder, onAdd }: { label: string; placeholder: string; onAdd: (v: string) => void }) {
  const [v, setV] = useState("");
  const submit = () => { const t = v.trim(); if (t) { onAdd(t); setV(""); } };
  return (
    <span className="inline-flex items-center gap-1">
      <input aria-label={label} placeholder={placeholder} value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()}
        className="h-7 w-28 rounded-md border border-border bg-card px-2 text-xs" />
      <button type="button" aria-label={`Confirm: ${label}`} onClick={submit} className="rounded p-1 hover:bg-muted"><Plus className="size-3.5" /></button>
    </span>
  );
}

function Rules() {
  const saved = useAsync(getRules, "rules");
  const [edited, setDraft] = useState<RulesConfig | null>(null);
  const draft = edited ?? saved.data;
  const [msg, setMsg] = useState<Msg>(null);
  const preview = usePreview(draft ? { rules: draft } : null);

  if (saved.status === "error" && !saved.data) return <ErrorCard error={saved.error} onRetry={saved.reload} />;
  if (!draft) return <SkeletonBlock rows={4} />;
  const dirty = edited !== null && JSON.stringify(edited) !== JSON.stringify(saved.data);

  return (
    <section aria-labelledby="rl" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 id="rl" className="text-lg font-semibold">Checks <span className="text-sm font-normal text-muted-foreground">one per kind of fraud · rules version {draft.version}</span></h2>
          <p className="max-w-prose text-sm text-muted-foreground">Each check decides one kind of fraud from the facts found in the call. The count shows on how many processed calls it would fire with your edits. Saving re-runs only the checks, the confidence and the decision; nothing is re-transcribed and the language model is not re-run.</p></div>
        <div className="flex gap-2">
          <Button size="sm" disabled={!dirty} onClick={async () => { try { const r = await putRules(draft); setMsg({ ok: true, text: `Saved. Re-running for ${r.rerun.n_calls} calls.` }); setDraft(null); saved.reload(); } catch (e) { setMsg(fail(e)); } }}><Save className="size-4" />Save checks</Button>
          <Button size="sm" variant="outline" disabled={!dirty} onClick={() => setDraft(null)}>Reset</Button>
        </div>
      </div>
      <MsgBox m={msg} />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {draft.rules.map((r, i) => {
          const params = Object.entries(r).filter(([k]) => k !== "criterion" && k !== "enabled");
          return (
            <Card key={r.criterion}>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: criterionColor(r.criterion) }} />{CRITERION_LABEL[r.criterion] ?? r.criterion}</CardTitle>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={r.enabled} onChange={(e) => { setMsg(null); setDraft((prev) => { const n = structuredClone(prev ?? saved.data!); n.rules[i].enabled = e.target.checked; return n; }); }} />On</label></CardHeader>
              <CardContent className="space-y-2">
                <p className="tabular text-sm">{preview.data ? <>would fire on <b>{preview.data.rule_fire_counts[r.criterion] ?? 0}</b> call(s)</> : <span className="text-muted-foreground">counting…</span>}</p>
                {params.length === 0 ? <CardDescription>Parameters come from rules.yaml (not defined in the mock).</CardDescription> : (
                  <details className="text-sm"><summary className="cursor-pointer text-xs text-muted-foreground">Parameters ({params.length})</summary>
                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">{params.map(([k, v]) => <Fragment key={k}><dt className="text-muted-foreground">{k}</dt><dd className="font-mono text-xs">{String(v)}</dd></Fragment>)}</dl>
                  </details>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
