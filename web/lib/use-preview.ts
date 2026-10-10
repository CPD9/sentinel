"use client";
import { useEffect, useState } from "react";
import { previewSettings } from "./data";
import type { PreviewRequest, PreviewResponse } from "./types";

/** Debounced POST /api/settings/preview. Nothing is saved. A failure only disables the impact panel. */
export function usePreview(req: PreviewRequest | null, delayMs = 350) {
  const key = JSON.stringify(req);
  const [res, setRes] = useState<{ key: string; data: PreviewResponse | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!req) return;
    let alive = true;
    const t = setTimeout(() => {
      previewSettings(req).then(
        (data) => alive && setRes({ key, data, error: null }),
        (e) => alive && setRes({ key, data: null, error: String(e?.message ?? e) }),
      );
    }, delayMs);
    return () => { alive = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, delayMs]);
  // Only a result for the current request counts; a stale one is never shown as current.
  const current = res?.key === key ? res : null;
  return { data: current?.data ?? null, error: current?.error ?? null, loading: !!req && !current };
}
