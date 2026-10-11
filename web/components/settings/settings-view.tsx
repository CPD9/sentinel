"use client";
import type { ReactNode } from "react";
import { isFixtures } from "@/lib/data";

/** Shared frame of a "no code" settings page: one plain sentence (the sub-tab names the page, no title), MOCK note. */
export function SettingsPage({ description, children }: { description: string; children: ReactNode }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{description}</p>
      {isFixtures && (
        <p role="note" className="rounded-md border border-review bg-review-bg px-3 py-2 text-xs text-review">
          MOCK: no settings files exist in fixtures. Defaults are invented, a hand-made what-if draft is a client-side approximation over invented sample calls, and saving is disabled.
        </p>
      )}
      {children}
    </div>
  );
}
