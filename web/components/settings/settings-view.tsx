"use client";
import { useState } from "react";
import { isFixtures } from "@/lib/data";
import { SettingsDraftProvider } from "@/lib/settings-draft";
import { cn } from "@/lib/utils";
import { Configuration } from "./configuration";
import { Tuning } from "./tuning";

export function SettingsView() {
  const [tab, setTab] = useState<"tuning" | "config">("tuning");
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Thresholds, keyword families and rules are edited here without code. Changes re-run only the cheap stages from cache.</p>
      </div>
      {isFixtures && (
        <p role="note" className="rounded-md border border-review bg-review-bg px-3 py-2 text-xs text-review">
          MOCK: no settings files exist in fixtures. Defaults are invented, a hand-made what-if draft is a client-side approximation over invented sample calls, and saving is disabled.
        </p>
      )}
      <div role="tablist" aria-label="Settings section" className="flex gap-1 border-b border-border">
        {([["tuning", "Tuning"], ["config", "Configuration"]] as const).map(([v, label]) => (
          <button key={v} role="tab" aria-selected={tab === v} onClick={() => setTab(v)}
            className={cn("border-b-2 px-3 py-2 text-sm", tab === v ? "border-foreground font-semibold" : "border-transparent text-muted-foreground")}>{label}</button>
        ))}
      </div>
      <SettingsDraftProvider>{tab === "tuning" ? <Tuning /> : <Configuration />}</SettingsDraftProvider>
    </div>
  );
}
