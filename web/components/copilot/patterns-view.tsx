"use client";

// "Patterns across calls": entities found in the validated facts and judge citations of every call (heuristic lexicon
// + n-gram matching, no LLM), which calls share them, and the same grounded chat over the whole run.
import { useEffect, useState } from "react";
import Link from "next/link";
import { Network, Sparkles } from "lucide-react";
import { CopilotChat } from "@/components/copilot/copilot-chat";
import { DecisionBadge } from "@/components/shell/badges";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CRITERION_LABEL } from "@/lib/colors";
import { getPatterns, type PatternHit, type PatternRow, type Patterns } from "@/lib/data-copilot";
import { fmtTime } from "@/lib/format";
import type { Criterion, Decision } from "@/lib/types";

const SUGGESTIONS = ["Which calls mention sharing information with family?", "Where do customers ask to split payments?", "Which calls involve non-public company results?"];
const GROUPS: { key: "criteria" | "securities" | "account_types" | "recipients"; title: string; desc: string }[] = [
  { key: "criteria", title: "Criteria", desc: "Judge criterion (flagged calls) and rules that fired" },
  { key: "recipients", title: "Third-party recipients", desc: "From facts marked as going to a third party" },
  { key: "securities", title: "Securities", desc: "Shares, bonds, funds, derivatives, takeovers" },
  { key: "account_types", title: "Account types & credentials", desc: "Accounts, custody, cards, PINs, e-banking" },
];

export function PatternsView() {
  const [data, setData] = useState<Patterns | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getPatterns().then(setData, (e: Error) => setError(e.message)); }, []);
  const decision = (id: string) => (data?.calls[id]?.decision ?? null) as Decision | null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-headline font-semibold tracking-tight"><Network className="size-5" aria-hidden />Patterns across calls</h1>
        <p className="text-sm text-muted-foreground">
          {data ? `${Object.keys(data.calls).length} calls. ` : ""}Entities and repeated phrasing from the validated facts and AI-judge citations. Heuristic matching, no LLM; click a call to open it at that passage.
        </p>
      </div>

      <section aria-labelledby="ask-all-h" className="space-y-3 rounded-[var(--radius-panel)] border border-border bg-card/60 p-4">
        <h2 id="ask-all-h" className="flex items-center gap-2 text-title font-semibold tracking-tight"><Sparkles className="size-4" aria-hidden />Ask across all calls</h2>
        <CopilotChat scope="all" suggestions={SUGGESTIONS} placeholder="Ask across all calls, e.g. “Who mentions a sister?”" />
      </section>

      {error && <p className="text-sm text-alarm">Patterns unavailable: {error}</p>}
      {!data && !error && <div className="grid gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-48" />)}</div>}
      {data && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {GROUPS.map((g) => (
              <Card key={g.key}>
                <CardHeader><div><CardTitle>{g.title}</CardTitle><CardDescription>{g.desc}</CardDescription></div></CardHeader>
                <CardContent className="space-y-3">
                  {data[g.key].length === 0 && <p className="text-sm text-muted-foreground">None found.</p>}
                  {data[g.key].map((r) => <EntityRow key={r.entity} row={r} label={g.key === "criteria" ? CRITERION_LABEL[r.entity as Criterion] ?? r.entity : r.entity} decision={decision} />)}
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader><div><CardTitle>Repeated phrasing</CardTitle><CardDescription>Four-word sequences shared by at least two calls (and at most a quarter of them)</CardDescription></div></CardHeader>
            <CardContent>
              {data.phrases.length === 0 ? <p className="text-sm text-muted-foreground">None found.</p> : (
                <ul className="divide-y divide-border">
                  {data.phrases.map((p) => (
                    <li key={p.phrase} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                      <span className="font-mono text-sm">“{p.phrase}”</span>
                      <span className="text-xs text-muted-foreground">{p.calls.length} calls</span>
                      <span className="flex flex-wrap gap-1.5">{p.calls.map((h) => <CallLink key={h.call_id} hit={h} decision={decision(h.call_id)} />)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">Method: {data.method}.</p>
        </>
      )}
    </div>
  );
}

function EntityRow({ row, label, decision }: { row: PatternRow; label: string; decision: (id: string) => Decision | null }) {
  const byCall = new Map<string, PatternHit>();
  for (const h of row.hits) if (!byCall.has(h.call_id)) byCall.set(h.call_id, h);
  const calls = [...byCall.values()].sort((a, b) => rank(decision(a.call_id)) - rank(decision(b.call_id)) || a.call_id.localeCompare(b.call_id));
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">{row.n_calls} call{row.n_calls === 1 ? "" : "s"} · {calls.filter((h) => decision(h.call_id) !== "no_alert").length} flagged</span>
      </summary>
      <ul className="mt-2 space-y-1.5 border-l border-border pl-3">
        {calls.map((h) => (
          <li key={h.call_id} className="flex flex-wrap items-center gap-2 text-sm">
            <CallLink hit={h} decision={decision(h.call_id)} />
            {h.quote && <span className="text-muted-foreground">“{h.quote.length > 120 ? `${h.quote.slice(0, 120)}…` : h.quote}”</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

const rank = (d: Decision | null) => (d === "alarm" ? 0 : d === "review" ? 1 : 2);

function CallLink({ hit, decision }: { hit: PatternHit; decision: Decision | null }) {
  const href = `/calls/${hit.call_id}${hit.segment_id ? `?seg=${encodeURIComponent(hit.segment_id)}` : ""}`;
  return (
    <Link href={href} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-0.5 font-mono text-xs hover:bg-muted">
      {hit.call_id}{hit.start_s != null && <span className="text-muted-foreground">{fmtTime(hit.start_s)}</span>}
      {decision && decision !== "no_alert" && <DecisionBadge decision={decision} size="sm" />}
    </Link>
  );
}
