"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

/** Native <dialog>: focus trap, Escape and backdrop come from the browser. `onClose` fires for Cancel and Escape. */
export function ConfirmDialog({ open, title, children, confirmLabel, busy, error, onConfirm, onClose }: {
  open: boolean; title: string; children: ReactNode; confirmLabel: string; busy?: boolean; error?: string | null;
  onConfirm: () => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="confirm-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border border-border bg-card p-0 text-foreground backdrop:bg-black/40">
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); onConfirm(); }} className="space-y-3 p-4">
        <h2 id="confirm-title" className="text-base font-semibold">{title}</h2>
        {children}
        {error && <p role="alert" className="rounded-md border border-alarm bg-alarm-bg p-2 text-sm text-alarm">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? "Applying…" : confirmLabel}</Button>
        </div>
      </form>
    </dialog>
  );
}
