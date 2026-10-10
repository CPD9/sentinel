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
        (e) => alive && setRes((p) => ({ key, data: p?.data ?? null, error: String(e?.message ?? e) })),
      );
    }, delayMs);
    return () => { alive = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, delayMs]);
  return { data: res?.data ?? null, error: res?.error ?? null, loading: !!req && res?.key !== key };
}
