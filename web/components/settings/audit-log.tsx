"use client";
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getAudit } from "@/lib/data";
import { componentLabel, fmtDateTime } from "@/lib/format";
import { patchComponents } from "@/lib/whatif-mock";
import { useAsync } from "@/lib/use-async";

/** Who changed the configuration, when, from what to what. Newest first. */
export function AuditLog({ refreshKey, bare }: { refreshKey: number; bare?: boolean }) {
  const state = useAsync(getAudit, `audit:${refreshKey}`);
  const body = (
    <>
        {state.status === "loading" && !state.data ? <SkeletonBlock rows={2} />
          : state.status === "error" && !state.data ? <ErrorCard error={state.error} onRetry={state.reload} title="Could not load the audit log" />
          : !state.data?.length ? <p className="text-sm text-muted-foreground">No configuration changes recorded yet.</p>
          : <ul className="space-y-2 text-sm">{state.data.map((a, i) => (
              <li key={`${a.ts}-${i}`} className="rounded-md border border-border p-2">
                <p><span className="tabular text-xs text-muted-foreground">{fmtDateTime(a.ts)}</span> · {a.action === "apply_suggestion" ? "suggestion applied" : "settings changed"}{a.n_flipped != null && ` · ${a.n_flipped} call(s) changed`}</p>
                <p className="text-xs">{patchComponents(a.patch).map(componentLabel).join(" · ") || "full document replaced"}</p>
                <p className="font-mono text-[11px] text-muted-foreground">{a.config_version_before} → {a.config_version_after}</p>
                {a.note && <p className="text-xs italic">“{a.note}”</p>}
              </li>))}</ul>}
    </>
  );
  if (bare) return body;
  return (
    <Card>
      <CardHeader><div><CardTitle>Audit log</CardTitle><CardDescription>Configuration changes, including applied suggestions.</CardDescription></div></CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  );
}
