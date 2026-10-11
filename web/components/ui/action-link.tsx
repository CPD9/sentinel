"use client";
// Violet outlined link button for moving between views ("Open full call", "← Overview"): visible but calmer than the
// filled primary button. Hover: the border lights up, a soft glow appears and the arrow nudges the way it points;
// click: a short press. All transitions are off with reduced motion.
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function ActionLink({ href, children, back = false, className }: { href: string; children: ReactNode; back?: boolean; className?: string }) {
  const arrow = cn("size-4 transition-transform duration-200 ease-out motion-reduce:transition-none",
    back ? "group-hover:-translate-x-1" : "group-hover:-translate-y-0.5 group-hover:translate-x-0.5");
  return (
    <Link href={href}
      className={cn("group inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 text-sm font-medium text-link",
        "transition-[background-color,border-color,box-shadow,transform] duration-200 ease-out",
        "hover:border-primary hover:bg-primary/20 hover:shadow-[0_0_0_3px_color-mix(in_srgb,var(--primary)_22%,transparent)]",
        "active:scale-[0.96] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none",
        className)}>
      {back && <ArrowLeft className={arrow} aria-hidden />}
      {children}
      {!back && <ArrowUpRight className={arrow} aria-hidden />}
    </Link>
  );
}
