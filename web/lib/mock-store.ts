"use client";
// Tracks which loaded documents are MOCK so the banner can stay visible (PRODUCT.md global rules).
import { useEffect, useSyncExternalStore } from "react";
import { isFixtures } from "./data";

const flagged = new Set<string>();
const listeners = new Set<() => void>();
let snapshot = 0;
const emit = () => { snapshot += 1; listeners.forEach((l) => l()); };

export function reportMock(key: string, isMock: boolean) {
  if (isMock === flagged.has(key)) return;
  if (isMock) flagged.add(key); else flagged.delete(key);
  emit();
}

export function useAnyMock(): boolean {
  useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb); },
    () => snapshot,
    () => 0,
  );
  return isFixtures || flagged.size > 0;
}

/** True when a document says it is MOCK: is_mock, or every version value is "MOCK". */
export function docIsMock(doc: unknown): boolean {
  if (!doc || typeof doc !== "object") return false;
  const d = doc as { is_mock?: boolean; versions?: Record<string, string | null> };
  if (d.is_mock) return true;
  const vals = d.versions ? Object.values(d.versions) : [];
  return vals.length > 0 && vals.every((v) => v === "MOCK");
}

export function useReportMock(key: string, doc: unknown) {
  const m = docIsMock(doc);
  useEffect(() => { reportMock(key, m); return () => reportMock(key, false); }, [key, m]);
}
