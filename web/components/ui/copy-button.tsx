"use client";
// Copy-to-clipboard with visible feedback: "copied ✓" for 1.5 s, or "copy failed" when the browser refuses.
import { useState } from "react";
import { cn } from "@/lib/utils";

export function CopyButton({ text, className }: { text: string; className?: string }) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  const copy = () => {
    const done = (s: "ok" | "fail") => { setState(s); setTimeout(() => setState("idle"), 1500); };
    if (!navigator.clipboard) { done("fail"); return; }
    navigator.clipboard.writeText(text).then(() => done("ok"), () => done("fail"));
  };
  return (
    <button type="button" onClick={copy} aria-live="polite"
      className={cn("shrink-0 rounded-full border border-border px-2.5 py-0.5 text-xs hover:bg-muted", state === "ok" && "border-foreground font-semibold", className)}>
      {state === "ok" ? "copied ✓" : state === "fail" ? "copy failed" : "copy"}
    </button>
  );
}
