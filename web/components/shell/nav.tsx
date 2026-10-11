"use client";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { useAnyMock } from "@/lib/mock-store";
import { DATA_SOURCE_LABEL, getRunInfo, isLocalRun } from "@/lib/data";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

// Nik's designs 05–07: three destinations. Settings holds Threshold | Keywords as tabs.
const LINKS = [
  { href: "/", label: "Alerts", match: (p: string) => p === "/" || p.startsWith("/calls") },
  { href: "/quality", label: "Quality", match: (p: string) => p.startsWith("/quality") },
  { href: "/settings/threshold", label: "Settings", match: (p: string) => p.startsWith("/settings") },
];

export function MockBanner() {
  const mock = useAnyMock();
  if (!mock) return null;
  return (
    <div role="status" className="border-b border-review bg-review-bg px-4 py-1.5 text-center text-xs font-semibold tracking-wide text-review">
      MOCK DATA — invented for development, not model output{DATA_SOURCE_LABEL.startsWith("fixtures") ? " (fixtures mode)" : ""}
    </div>
  );
}

/** Local-run fallback: a neutral strip that says where the data comes from and what it cannot do. Real data, not MOCK. */
function LocalRunBanner() {
  const info = useAsync(getRunInfo, "run-info");
  if (!isLocalRun) return null;
  const r = info.data;
  const bits = r ? [
    `Real run ${r.run_id}`,
    r.mode === "reference" ? "reference transcripts (no audio timestamps)" : "speech-recognition transcripts",
    r.notes.some((n) => /dry-run/i.test(n)) ? "trigger dry-run" : null,
  ].filter(Boolean) : ["Real run"];
  return (
    <div role="status" className="border-b border-border bg-muted px-4 py-1.5 text-center text-xs text-muted-foreground">
      {bits.join(" · ")} · read from local files (read-only fallback, not via the API): previews are exact, saving is off.
    </div>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);
  const dark = mounted && resolvedTheme === "dark";
  return (
    <Button variant="ghost" size="icon" aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} onClick={() => setTheme(dark ? "light" : "dark")}>
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}

export function TopNav() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-30 bg-background/95 backdrop-blur">
      <MockBanner />
      <LocalRunBanner />
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-4 px-4 sm:gap-8 sm:px-6">
        <Link href="/" className="text-2xl font-bold tracking-[-0.02em]" aria-label="Sentinel, alerts">Sentinel</Link>
        <span className="hidden text-xs text-muted-foreground md:inline" title="Where the data on screen comes from">
          self-hosted · {DATA_SOURCE_LABEL}
        </span>
        <nav className="-my-2 ml-auto flex min-w-0 gap-1 overflow-x-auto py-2 sm:gap-4" aria-label="Main">
          {LINKS.map((l) => {
            const active = l.match(path);
            return (
              <Link key={l.href} href={l.href} aria-current={active ? "page" : undefined}
                className={cn("whitespace-nowrap border-b-2 px-1.5 py-1 text-[17px] transition-colors",
                  active ? "border-foreground font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
                {l.label}
              </Link>
            );
          })}
        </nav>
        <ThemeToggle />
      </div>
    </header>
  );
}
