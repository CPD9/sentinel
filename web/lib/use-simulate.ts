"use client";
import { useEffect, useState } from "react";
import { simulate } from "./data";
import type { Patch, SimulationResult } from "./types";

/** Debounced POST /api/simulate. Nothing is saved. A stale result is never shown as current; a failure only disables the panel. */
export function useSimulate(patch: Patch | null, delayMs = 300) {
  const key = JSON.stringify(patch);
  const [res, setRes] = useState<{ key: string; data: SimulationResult | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!patch) return;
    let alive = true;
    const t = setTimeout(() => {
      simulate(patch).then(
        (data) => alive && setRes({ key, data, error: null }),
        (e) => alive && setRes({ key, data: null, error: Array.isArray(e?.detail) ? e.detail.join("; ") : String(e?.message ?? e) }),
      );
    }, delayMs);
    return () => { alive = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, delayMs]);
  const current = res?.key === key ? res : null;
  // Keep the previous good result visible (marked stale) while a new one loads, so the panel does not flicker while dragging.
  const last = res?.data ?? null;
  return { data: current?.data ?? null, stale: current ? null : last, error: current?.error ?? null, loading: !!patch && !current };
}
