"use client";
import { use } from "react";
import { InboxView } from "@/components/inbox/inbox-view";

/** Overview. `?call=<id>` picks the call shown in the right panel, so a selection survives a reload and can be shared. */
export default function Page({ searchParams }: { searchParams: Promise<{ call?: string }> }) {
  const q = use(searchParams);
  return <InboxView selected={q.call ?? null} />;
}
