"use client";

// "Ask about this call": grounded chat for the call page. Citations drive the page's shared player via onCite.
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { CopilotChat } from "@/components/copilot/copilot-chat";

const SUGGESTIONS = ["Why was this flagged?", "Who said it?", "What would make this harmless?"];

export function AskCallPanel({ callId, onCite }: { callId: string; onCite: (segmentIds: string[]) => void }) {
  return (
    <section aria-labelledby="ask-h" className="stage-in space-y-3 rounded-[var(--radius-panel)] border border-border bg-card/60 p-4" style={{ "--i": 1 } as React.CSSProperties}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="ask-h" className="flex items-center gap-2 text-title font-semibold tracking-tight"><Sparkles className="size-4" aria-hidden />Ask about this call</h2>
        <Link href="/patterns" className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">Patterns across calls →</Link>
      </div>
      <CopilotChat scope="call" callId={callId} suggestions={SUGGESTIONS} onCite={onCite} placeholder="Ask about this call, e.g. “Did the advisor refuse?”" />
    </section>
  );
}
