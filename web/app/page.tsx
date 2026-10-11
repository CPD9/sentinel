"use client";
import { use } from "react";
import { InboxView } from "@/components/inbox/inbox-view";

/**
 * Overview. `?call=<id>` is the call open in the right panel (empty = closed), `?tab=<group>` the list's tab when no
 * call says it, `?view=table` the full table. All in the URL, so a view survives a reload and can be shared.
 */
export default function Page({ searchParams }: { searchParams: Promise<{ call?: string; tab?: string; view?: string }> }) {
  const q = use(searchParams);
  return <InboxView selected={q.call ?? null} tab={q.tab ?? null} view={q.view === "table" ? "table" : "list"} />;
}
