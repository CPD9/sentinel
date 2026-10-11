"use client";
import { Save, X } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CRITERION_LABEL, criterionColor } from "@/lib/colors";
import { InfoTip } from "@/components/ui/info-tip";
import { ApiError, getKeywords, getRules, isFixtures, isLocalRun, putKeywords, putRules } from "@/lib/data";
import { DECISION_LABEL } from "@/lib/explain";
import { cn } from "@/lib/utils";
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
      <details className="group rounded-2xl border border-border">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3.5 text-sm font-semibold [&::-webkit-details-marker]:hidden">
          <span aria-hidden className="transition-transform group-open:rotate-90 motion-reduce:transition-none">›</span>Checks
          <span className="font-normal text-muted-foreground">one rule per kind of fraud (advanced)</span>
        </summary>
        <div className="border-t border-border p-5"><Rules /></div>
      </details>
    </div>
  );
}

/** What changed between the saved keyword document and the draft, in officer words. */
function describe(saved: KeywordsConfig, draft: KeywordsConfig): string[] {
  const out: string[] = [];
  const famLabel = (k: string) => (draft.families[k] ?? saved.families[k]) ? familyLabel(k, draft.families[k] ?? saved.families[k]) : k;
  for (const [k, f] of Object.entries(draft.families)) {
    const before = saved.families[k];
    const words = (x?: KeywordsConfig["families"][string]) => new Set(x ? [...x.terms, ...Object.values(x.variants).flat()] : []);
    const b = words(before), d = words(f);
    for (const w of d) if (!b.has(w)) out.push(`Adding “${w}” to ${famLabel(k)}`);
    for (const w of b) if (!d.has(w)) out.push(`Removing “${w}” from ${famLabel(k)}`);
  }
  if (draft.fuzzy_threshold !== saved.fuzzy_threshold) out.push(`Match strictness ${saved.fuzzy_threshold.toFixed(2)} → ${draft.fuzzy_threshold.toFixed(2)}`);
  return out;
}
const familyLabel = (key: string, f: { criterion: string; label?: string }) => CRITERION_LABEL[f.criterion as keyof typeof CRITERION_LABEL] ?? f.label ?? key;

// Settings → Keywords (Nik's design 07): the families as chips on the left, what the change would do on the right.
function Keywords() {
  const saved = useAsync(getKeywords, "keywords");
  const [edited, setDraft] = useState<KeywordsConfig | null>(null);
  const draft = edited ?? saved.data;
  const [msg, setMsg] = useState<Msg>(null);
  const [newWord, setNewWord] = useState("");
  const [family, setFamily] = useState("");
  const preview = usePreview(draft ? { keywords: draft } : null);

  if (saved.status === "error" && !saved.data) return <ErrorCard error={saved.error} onRetry={saved.reload} />;
  if (!draft || !saved.data) return <SkeletonBlock rows={5} />;
  const dirty = edited !== null && JSON.stringify(edited) !== JSON.stringify(saved.data);
  const changes = dirty ? describe(saved.data, draft) : [];
  const count = (fam: string, term: string) => (preview.data ? preview.data.keyword_hit_counts[fam]?.[term] ?? 0 : undefined);
  const known = (fam: string, w: string) => { const f = saved.data!.families[fam]; return !!f && (f.terms.includes(w) || Object.values(f.variants).some((v) => v.includes(w))); };
  const mutate = (fn: (d: KeywordsConfig) => void) => { setMsg(null); setDraft((prev) => { const n = structuredClone(prev ?? saved.data!); fn(n); return n; }); };
  const fam = family || Object.keys(draft.families)[0];
  const add = () => { const w = newWord.trim(); if (!w || !fam) return; mutate((d) => { const f = d.families[fam]; if (!f.terms.includes(w)) { f.terms.push(w); f.variants[w] ??= []; } }); setNewWord(""); };
  const readOnly = isFixtures || isLocalRun;
  const saveTitle = isLocalRun ? "Read-only local run: saving needs the API" : isFixtures ? "Disabled in fixtures mode (MOCK)" : undefined;
  const changed = preview.data?.changed ?? [];

  return (
    <section aria-label="Keywords" className="grid gap-5 lg:grid-cols-2">
      <div className="elevated stage-in min-w-0 space-y-6 rounded-[var(--radius-panel)] p-6">
        {Object.entries(draft.families).map(([name, f]) => (
          <div key={name} className="space-y-2.5">
            <h3 className="eyebrow flex items-center gap-2"><span aria-hidden className="inline-block size-2 rounded-full" style={{ background: criterionColor(f.criterion) }} />{familyLabel(name, f)}</h3>
            <ul className="flex flex-wrap gap-2">
              {f.terms.map((term) => (
                <Fragment key={term}>
                  <Chip word={term} hits={count(name, term)} fresh={!known(name, term)} onRemove={() => mutate((d) => { const x = d.families[name]; x.terms = x.terms.filter((t) => t !== term); delete x.variants[term]; })} />
                  {(f.variants[term] ?? []).map((v) => (
                    <Chip key={v} word={v} variantOf={term} hits={count(name, v)} fresh={!known(name, v)} onRemove={() => mutate((d) => { d.families[name].variants[term] = d.families[name].variants[term].filter((x) => x !== v); })} />
                  ))}
                </Fragment>
              ))}
            </ul>
          </div>
        ))}
        <div className="space-y-2 border-t border-border pt-5">
          <label htmlFor="kw-new" className="text-sm text-muted-foreground">Add a keyword</label>
          <div className="flex flex-wrap gap-3">
            <input id="kw-new" value={newWord} onChange={(e) => setNewWord(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="e.g. nöd ufschriibe"
              className="h-11 min-w-48 flex-1 rounded-xl border border-border bg-background px-4 text-body" />
            <select aria-label="Family" value={fam} onChange={(e) => setFamily(e.target.value)} className="h-11 rounded-xl border border-border bg-background px-3 text-body">
              {Object.entries(draft.families).map(([k, f]) => <option key={k} value={k}>{familyLabel(k, f)}</option>)}
            </select>
            <button type="button" onClick={add} disabled={!newWord.trim()} title={newWord.trim() ? undefined : "Type a word first"}
              className="inline-flex h-11 items-center rounded-full border border-foreground/60 px-6 font-semibold hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40">
              Add to {familyLabel(fam, draft.families[fam])}
            </button>
          </div>
          <label className="flex flex-wrap items-center gap-3 pt-2 text-sm text-muted-foreground">Match strictness
            <input type="range" min={0.5} max={1} step={0.01} value={draft.fuzzy_threshold} onChange={(e) => mutate((d) => { d.fuzzy_threshold = +e.target.value; })} />
            <span className="tabular font-semibold text-foreground">{draft.fuzzy_threshold.toFixed(2)}</span>
            <InfoTip term="match_strictness" />
          </label>
        </div>
      </div>

      <div className="elevated stage-in flex min-w-0 flex-col gap-5 rounded-[var(--radius-panel)] p-6" style={{ "--i": 1 } as React.CSSProperties} aria-live="polite">
        <h3 className="eyebrow">What this change would do</h3>
        <MsgBox m={msg} />
        {!dirty ? (
          <p className="text-body text-muted-foreground">Add or remove a word: every call of this run is checked again with the draft, and the calls whose decision changes are listed here. The small number on each word is how many transcript passages it matches.</p>
        ) : preview.error ? <p role="alert" className="text-sm text-alarm">The effect could not be computed: {preview.error}</p>
          : (
            <>
              <p className="text-lead">{changes.join(". ")}{changes.length ? " " : ""}
                {preview.loading ? <span className="text-muted-foreground">…</span> : preview.data?.note ? <span className="text-muted-foreground">— its hit counts are updated on the left.</span> : <>changes <b>{changed.length} call{changed.length === 1 ? "" : "s"}</b>.</>}
              </p>
              {preview.data?.note && <p className="text-sm text-review">{preview.data.note}</p>}
              {changed.length > 0 && (
                <ul className="divide-y divide-border border-y border-border">
                  {changed.map((c, i) => (
                    <li key={c.call_id} className="stage-in flex items-center justify-between gap-3 py-3" style={{ "--i": Math.min(i, 8) } as React.CSSProperties}>
                      <Link href={`/calls/${c.call_id}`} className="font-mono underline-offset-2 hover:underline">{c.call_id}</Link>
                      <span className="text-sm text-muted-foreground">{DECISION_LABEL[c.decision_before]} → <b className={c.decision_after === "alarm" ? "text-alarm" : c.decision_after === "review" ? "text-review" : "text-foreground"}>{DECISION_LABEL[c.decision_after]}</b></span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-sm text-muted-foreground">Open any call to check the word is used suspiciously, not innocently. A keyword alone never raises an alert; it only adds weight next to a fact.</p>
            </>
          )}
        <div className="mt-auto flex flex-wrap items-center gap-3 border-t border-border pt-5">
          <button type="button" disabled={!dirty || readOnly} title={saveTitle}
            onClick={async () => { try { const r = await putKeywords(draft); setMsg({ ok: true, text: `Saved. Keywords, checks and decisions are re-made for ${r.rerun.n_calls} calls.` }); setDraft(null); saved.reload(); } catch (e) { setMsg(fail(e)); } }}
            className="inline-flex h-11 items-center gap-2 rounded-full bg-primary px-6 font-semibold text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"><Save className="size-4" aria-hidden />Save keywords</button>
          <button type="button" disabled={!dirty} onClick={() => { setDraft(null); setMsg(null); }}
            className="inline-flex h-11 items-center rounded-full border border-foreground/60 px-6 font-semibold hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40">Reset</button>
          {dirty && readOnly && <span className="text-sm text-muted-foreground">{saveTitle}</span>}
        </div>
      </div>
    </section>
  );
}

function Chip({ word, hits, fresh, variantOf, onRemove }: { word: string; hits: number | undefined; fresh: boolean; variantOf?: string; onRemove: () => void }) {
  return (
    <li title={variantOf ? `Swiss German variant of “${variantOf}”` : undefined}
      className={cn("stage-in inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-body",
        fresh ? "bg-review text-[#1a1300] font-semibold" : variantOf ? "border border-dashed border-border" : "bg-muted")}>
      <span lang="gsw">{word}</span>
      <span className={cn("tabular text-xs", fresh ? "" : "text-muted-foreground")} aria-label={`${hits ?? "unknown"} matching passages`}>{hits ?? "…"}</span>
      <button type="button" aria-label={`Remove ${word}`} onClick={onRemove} className="rounded-full p-0.5 hover:bg-foreground/10"><X className="size-3.5" /></button>
      {fresh && <span className="text-xs">· new</span>}
    </li>
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
