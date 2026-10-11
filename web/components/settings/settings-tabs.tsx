"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/sensitivity", label: "Sensitivity" },
  { href: "/keywords", label: "Keywords & checks" },
];

/** Sub-tabs of the Settings tab: a small segmented switch on top of both settings pages. */
export function SettingsTabs() {
  const path = usePathname();
  return (
    <nav aria-label="Settings" className="inline-flex gap-1 rounded-lg border border-border bg-muted/60 p-1">
      {TABS.map((t) => {
        const active = path.startsWith(t.href);
        return (
          <Link key={t.href} href={t.href} aria-current={active ? "page" : undefined}
            className={cn("whitespace-nowrap rounded-md px-3 py-1 text-sm transition-colors",
              active ? "bg-card font-semibold text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
