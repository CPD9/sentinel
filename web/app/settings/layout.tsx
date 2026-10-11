"use client";
// Settings frame (Nik's designs 05 and 07): one title, one plain sentence, Threshold | Keywords tabs.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/settings/threshold", label: "Threshold", lead: "Choose how sensitive the system is. Changes are previewed first and applied only when you save." },
  { href: "/settings/keywords", label: "Keywords", lead: "Edit the words and phrases the system looks for. No code needed." },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const active = TABS.find((t) => path.startsWith(t.href)) ?? TABS[0];
  return (
    <div className="stage-in space-y-6">
      <div className="space-y-1">
        <h1 className="text-headline font-semibold tracking-tight">Settings</h1>
        <p className="text-body text-muted-foreground">{active.lead}</p>
      </div>
      <nav aria-label="Settings" className="border-b border-border">
        <ul className="flex gap-6">
          {TABS.map((t) => (
            <li key={t.href}>
              <Link href={t.href} aria-current={t === active ? "page" : undefined}
                className={cn("-mb-px block border-b-2 pb-2 text-lead", t === active ? "border-foreground font-semibold" : "border-transparent text-muted-foreground hover:text-foreground")}>
                {t.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {children}
    </div>
  );
}
