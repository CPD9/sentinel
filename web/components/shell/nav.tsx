"use client";
import { Gauge, LayoutDashboard, Moon, Settings, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { ImportCallsButton, ImportMessage } from "@/components/inbox/upload";
import { useAnyMock } from "@/lib/mock-store";
import { DATA_MODE } from "@/lib/data";
import { cn } from "@/lib/utils";

// Main tabs. Settings holds two sub-pages (Sensitivity, Keywords & checks) and stays active on both.
// Each icon has its own hover move (globals.css): the dashboard tiles pop, the gauge needle swings, the gear turns.
const LINKS: { href: string; label: string; short?: string; match: string[]; icon: typeof Gauge; anim: string }[] = [
  { href: "/", label: "Overview", match: ["/calls"], icon: LayoutDashboard, anim: "nav-ic-pop" },
  { href: "/quality", label: "Detection quality", short: "Quality", match: ["/quality"], icon: Gauge, anim: "nav-ic-swing" },
  { href: "/sensitivity", label: "Settings", match: ["/settings", "/sensitivity", "/keywords"], icon: Settings, anim: "nav-ic-turn" },
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

/**
 * Light/dark switch: a small pill whose knob slides over and turns its icon. The theme flips just after the slide,
 * because next-themes switches all CSS transitions off at the moment the theme changes.
 */
function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);
  const [pending, setPending] = useState<boolean | null>(null);
  const dark = pending ?? (mounted && resolvedTheme === "dark");
  const flip = () => {
    const next = !dark;
    setPending(next);
    window.setTimeout(() => { setTheme(next ? "dark" : "light"); setPending(null); }, 220);
  };
  return (
    <button type="button" role="switch" aria-checked={dark} aria-label="Dark mode" onClick={flip}
      className="relative h-7 w-[52px] shrink-0 rounded-full border border-border bg-muted transition-colors hover:border-primary/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
      <Sun className="absolute left-[7px] top-1/2 size-3 -translate-y-1/2 text-muted-foreground/60" aria-hidden />
      <Moon className="absolute right-[7px] top-1/2 size-3 -translate-y-1/2 text-muted-foreground/60" aria-hidden />
      <span aria-hidden className={cn(
        "absolute left-[3px] top-1/2 flex size-5 -translate-y-1/2 items-center justify-center rounded-full shadow-[0_1px_3px_rgba(0,0,0,0.3)]",
        "transition-[transform,background-color] duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)] motion-reduce:transition-none",
        dark ? "translate-x-6 bg-primary" : "translate-x-0 bg-card", !mounted && "opacity-0")}>
        <Sun className={cn("absolute size-3 text-review transition-all duration-300 motion-reduce:transition-none", dark ? "rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100")} />
        <Moon className={cn("absolute size-3 text-primary-foreground transition-all duration-300 motion-reduce:transition-none", dark ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-0 opacity-0")} />
      </span>
    </button>
  );
}

export function TopNav() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur">
      <MockBanner />
      <div className="mx-auto flex h-12 max-w-[1400px] items-center gap-2 px-4 sm:gap-6">
        <nav className="-my-2 flex min-w-0 gap-1 overflow-x-auto py-2" aria-label="Main">
          {LINKS.map((l) => {
            const active = (l.href === "/" && path === "/") || l.match.some((m) => path.startsWith(m));
            return (
              <Link key={l.href} href={l.href} aria-current={active ? "page" : undefined} aria-label={l.label}
                className={cn("nav-tab inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm sm:px-3",
                  active ? "bg-primary/15 font-semibold text-link" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
                <l.icon className={cn("size-4 shrink-0", l.anim)} aria-hidden />
                {/* phones: the active tab shows its (short) name, the others only their icon */}
                <span className={cn(!active && "hidden sm:inline")}>
                  {l.short ? <><span className="sm:hidden">{l.short}</span><span className="hidden sm:inline">{l.label}</span></> : l.label}
                </span>
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-2 text-xs text-muted-foreground sm:gap-3">
          <span className="hidden lg:inline">self-hosted · {DATA_MODE}</span>
          <ThemeToggle />
          <ImportCallsButton />
        </div>
      </div>
      <ImportMessage />
    </header>
  );
}
