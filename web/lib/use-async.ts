"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./data";

export type AsyncState<T> =
  | { status: "loading"; data: T | null; error: null }
  | { status: "ok"; data: T; error: null }
  | { status: "error"; data: T | null; error: ApiError };
export type Loadable<T> = AsyncState<T> & { reload: () => void };

interface Settled<T> { key: string; reqKey: string; data: T | null; error: ApiError | null }

/**
 * Loads on `key` change (and on reload()). Keeps the last good data for the same key when a reload fails.
 * Status is derived, so no state is set synchronously inside the effect.
 */
export function useAsync<T>(fn: () => Promise<T>, key: string): Loadable<T> {
  const [tick, setTick] = useState(0);
  const [res, setRes] = useState<Settled<T> | null>(null);
  const reqKey = `${key}#${tick}`;
  useEffect(() => {
    let alive = true;
    fn().then(
      (data) => alive && setRes({ key, reqKey, data, error: null }),
      (e) => alive && setRes((prev) => ({
        key, reqKey, data: prev?.key === key ? prev.data : null,
        error: e instanceof ApiError ? e : new ApiError(0, "internal", String(e?.message ?? e)),
      })),
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reqKey]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const sameKey = res?.key === key;
  const data = sameKey ? res!.data : null;
  const settled = res?.reqKey === reqKey;
  if (!settled) return { status: "loading", data, error: null, reload } as Loadable<T>;
  if (res!.error) return { status: "error", data, error: res!.error, reload };
  return { status: "ok", data: res!.data as T, error: null, reload };
}
