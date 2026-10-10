import * as React from "react";
import { cn } from "@/lib/utils";

export function Badge({ className, style, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-border px-2 py-0.5 text-xs font-medium", className)}
      style={style}
      {...props}
    />
  );
}
