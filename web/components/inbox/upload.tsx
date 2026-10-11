"use client";
import { Upload, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ApiError, uploadCall } from "@/lib/data";

/**
 * Import of .wav files → POST /api/calls (one request per file), shared by the whole app: the "Import calls" button in
 * the nav (every tab) and the page-wide drop zone on the Overview use the same state. One file opens its live
 * processing view; several files go to the Overview. `imported` counts finished imports so the call list can reload.
 */
interface UploadState { send: (files: FileList | File[]) => Promise<void>; busy: boolean; msg: string | null; clear: () => void; imported: number }
const UploadCtx = createContext<UploadState | null>(null);

export function UploadProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [imported, setImported] = useState(0);

  const send = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files);
    const wavs = list.filter((f) => f.name.toLowerCase().endsWith(".wav"));
    setMsg(wavs.length !== list.length ? "Only .wav files are accepted." : null);
    if (!wavs.length) return;
    setBusy(true);
    try {
      let last: string | null = null;
      for (const f of wavs) last = (await uploadCall(f)).call_id;
      setImported((n) => n + 1);
      router.push(last && wavs.length === 1 ? `/calls/${last}/processing` : "/");
    } catch (e) {
      setMsg(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  }, [router]);

  const clear = useCallback(() => setMsg(null), []);
  const value = useMemo(() => ({ send, busy, msg, clear, imported }), [send, busy, msg, clear, imported]);
  return <UploadCtx.Provider value={value}>{children}</UploadCtx.Provider>;
}

export function useUpload(): UploadState {
  const c = useContext(UploadCtx);
  if (!c) throw new Error("useUpload needs <UploadProvider>");
  return c;
}

/** "Import calls": small button at the right of the nav. In production calls arrive automatically; this is the manual path. */
export function ImportCallsButton() {
  const { send, busy } = useUpload();
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input ref={input} type="file" accept=".wav,audio/wav" multiple hidden
        onChange={(e) => { if (e.target.files) void send(e.target.files); e.target.value = ""; }} />
      <Button size="sm" disabled={busy} onClick={() => input.current?.click()}
        title="Import .wav recordings (or drop them anywhere on the Overview)">
        <Upload className="size-3.5" aria-hidden />
        <span className="sr-only sm:not-sr-only">{busy ? "Importing…" : "Import calls"}</span>
      </Button>
    </>
  );
}

/** Import error, shown as one line under the nav until dismissed. */
export function ImportMessage() {
  const { msg, clear } = useUpload();
  if (!msg) return null;
  return (
    <div role="alert" className="border-t border-border bg-alarm-bg">
      <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-1.5 text-xs text-alarm">
        <span className="min-w-0 flex-1">Import failed. {msg}</span>
        <button type="button" onClick={clear} aria-label="Dismiss" className="rounded p-0.5 hover:bg-muted"><X className="size-3.5" /></button>
      </div>
    </div>
  );
}
