"use client";
import { Moon, ShieldCheck, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { useAnyMock } from "@/lib/mock-store";
import { DATA_MODE } from "@/lib/data";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Inbox" },
  { href: "/settings", label: "Settings" },
  { href: "/quality", label: "Quality lab" },
];

export function MockBanner() {
  const mock = useAnyMock();
  if (!mock) return null;
  return (
    <div role="status" className="border-b border-review bg-review-bg px-4 py-1.5 text-center text-xs font-semibold tracking-wide text-review">
      MOCK DATA — invented for development, not model output{DATA_MODE === "fixtures" ? " (fixtures mode)" : ""}
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
    <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur">
      <MockBanner />
      <div className="mx-auto flex h-12 max-w-[1400px] items-center gap-3 px-4 sm:gap-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <ShieldCheck className="size-5" aria-hidden /><span className="hidden sm:inline">SENTINEL</span>
        </Link>
        <nav className="flex gap-1" aria-label="Main">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" || path.startsWith("/calls") : path.startsWith(l.href);
            return (
              <Link key={l.href} href={l.href} aria-current={active ? "page" : undefined}
                className={cn("whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm sm:px-3", active ? "bg-muted font-semibold" : "text-muted-foreground hover:bg-muted")}>
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <span className="hidden sm:inline">self-hosted · {DATA_MODE}</span>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
