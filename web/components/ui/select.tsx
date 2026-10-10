import * as React from "react";
import { cn } from "@/lib/utils";

/** Native <select> with the app's styling. Accessible by default. */
export function Select({ className, label, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      {label}
      <select className={cn("h-8 rounded-md border border-border bg-card px-2 text-sm text-foreground", className)} {...props}>
        {children}
      </select>
    </label>
  );
}
