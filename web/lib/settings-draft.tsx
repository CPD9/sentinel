"use client";
// The officer's unsaved what-if draft, shared by the Tuning sliders, the "detection switches", the suggestions' Preview
// button and the impact panel. Nothing here is saved: it only becomes a Patch for POST /api/simulate (or a confirmed save).
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { KeywordReview, Patch, Thresholds } from "./types";

interface Draft { thresholds: Thresholds | null; families: string[]; rules: string[]; keywordReview: KeywordReview | null }
const EMPTY: Draft = { thresholds: null, families: [], rules: [], keywordReview: null };

interface Ctx {
  draft: Draft;
  setThreshold(saved: Thresholds, k: "alarm" | "review" | "confidence_gate", v: number): void;
  /** judge mode: keyword hits alone may raise a call to review (thresholds.keyword_review) */
  setKeywordReview(v: KeywordReview): void;
  toggleFamily(name: string): void;
  toggleRule(criterion: string): void;
  loadPatch(saved: Thresholds, patch: Patch): void;
  reset(): void;
  /** The draft as a patch against `saved`: only thresholds that differ, plus the switched-off families and rules. Null = no change. */
  toPatch(saved: Thresholds | null): Patch | null;
}
const DraftCtx = createContext<Ctx | null>(null);
const GAP = 0.01;
const toggle = (xs: string[], x: string) => (xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x].sort());

export function SettingsDraftProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const setThreshold = useCallback((saved: Thresholds, k: "alarm" | "review" | "confidence_gate", v: number) => setDraft((d) => {
    const n = { ...(d.thresholds ?? saved), [k]: Math.round(v * 100) / 100 };
    if (k === "alarm") n.alarm = Math.max(n.alarm, n.review + GAP);
    if (k === "review") n.review = Math.min(n.review, n.alarm - GAP);
    return { ...d, thresholds: n };
  }), []);
  const loadPatch = useCallback((saved: Thresholds, p: Patch) => setDraft({
    thresholds: p.thresholds ? ({ ...saved, ...p.thresholds } as Thresholds) : null,
    keywordReview: p.thresholds?.keyword_review ?? null,
    families: p.keywords && "disable_families" in p.keywords ? [...p.keywords.disable_families].sort() : [],
    rules: p.rules && "disable" in p.rules ? [...p.rules.disable].sort() : [],
  }), []);
  const value = useMemo<Ctx>(() => ({
    draft, setThreshold, loadPatch,
    toggleFamily: (n) => setDraft((d) => ({ ...d, families: toggle(d.families, n) })),
    toggleRule: (c) => setDraft((d) => ({ ...d, rules: toggle(d.rules, c) })),
    reset: () => setDraft(EMPTY),
    setKeywordReview: (v) => setDraft((d) => ({ ...d, keywordReview: v })),
    toPatch: (saved) => {
      const patch: Patch = {};
      if (draft.thresholds && saved) {
        const diff = (["alarm", "review", "confidence_gate"] as const).filter((k) => draft.thresholds![k] !== saved[k]);
        if (diff.length) patch.thresholds = Object.fromEntries(diff.map((k) => [k, draft.thresholds![k]]));
      }
      const kr = draft.keywordReview, kr0 = saved?.keyword_review ?? { enabled: false, min_segments: 2 };
      if (kr && (kr.enabled !== kr0.enabled || (kr.enabled && kr.min_segments !== kr0.min_segments))) patch.thresholds = { ...(patch.thresholds ?? {}), keyword_review: kr };
      if (draft.families.length) patch.keywords = { disable_families: draft.families };
      if (draft.rules.length) patch.rules = { disable: draft.rules };
      return Object.keys(patch).length ? patch : null;
    },
  }), [draft, setThreshold, loadPatch]);
  return <DraftCtx.Provider value={value}>{children}</DraftCtx.Provider>;
}

export function useSettingsDraft(): Ctx {
  const c = useContext(DraftCtx);
  if (!c) throw new Error("useSettingsDraft needs <SettingsDraftProvider>");
  return c;
}
