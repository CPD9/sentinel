import { AlertCircle, Inbox, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ApiError } from "@/lib/data";

/** The three states every surface has: loading skeleton in final layout, one-sentence empty state, error with retry. */
export function SkeletonBlock({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={className} aria-busy="true" aria-label="loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="mb-3 h-5" />)}
    </div>
  );
}

export function EmptyState({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Card className="flex flex-col items-center gap-2 border-dashed p-8 text-center text-sm text-muted-foreground">
      <Inbox className="size-5" aria-hidden />
      <p>{children}</p>
      {action}
    </Card>
  );
}

export function ErrorCard({ error, title = "Could not load this", onRetry }: { error: ApiError | Error; title?: string; onRetry?: () => void }) {
  const code = "code" in error ? (error as ApiError).code : "error";
  return (
    <Card role="alert" className="border-alarm/50 p-4 text-sm">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-alarm" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{title}</p>
          <p className="mt-1 break-words text-muted-foreground"><code className="font-mono text-xs">{code}</code> · {error.message}</p>
        </div>
        {onRetry && <Button variant="outline" size="sm" onClick={onRetry}><RefreshCw className="size-3.5" />Retry</Button>}
      </div>
    </Card>
  );
}

/** A missing optional block is an empty state, not an error. */
export function NotAvailable({ children }: { children: React.ReactNode }) {
  return <EmptyState>{children}</EmptyState>;
}

import type { Loadable } from "@/lib/use-async";

/** Renders the 3 states for one document. 404 = "not available" (empty), anything else = error with retry. */
export function DocGate<T>({
  state, unavailable, rows = 5, children,
}: { state: Loadable<T>; unavailable: string; rows?: number; children: (data: T) => React.ReactNode }) {
  if (state.data) return <>{state.status === "error" && <p className="mb-2 text-xs text-review">Reload failed; showing the last good data.</p>}{children(state.data)}</>;
  if (state.status === "loading") return <SkeletonBlock rows={rows} />;
  if (state.status === "error") {
    return state.error.status === 404 ? <NotAvailable>{unavailable}</NotAvailable> : <ErrorCard error={state.error} onRetry={state.reload} />;
  }
  return null;
}
