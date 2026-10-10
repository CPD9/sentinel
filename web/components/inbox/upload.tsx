"use client";
import { Plus } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ApiError, uploadCall } from "@/lib/data";

/** Upload of .wav files → POST /api/calls (one request per file). One file opens its live processing view. */
export function useWavUpload(onUploaded: () => void) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const send = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files);
    const wavs = list.filter((f) => f.name.toLowerCase().endsWith(".wav"));
    setMsg(wavs.length !== list.length ? "Only .wav files are accepted." : null);
    if (!wavs.length) return;
    setBusy(true);
    try {
      let last: string | null = null;
      for (const f of wavs) last = (await uploadCall(f)).call_id;
      onUploaded();
      if (last && wavs.length === 1) router.push(`/calls/${last}/processing`);
    } catch (e) {
      setMsg(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  }, [onUploaded, router]);

  return { send, busy, msg };
}

/** "Analyse a call" button. In production calls arrive automatically; this is the manual path for the demo. */
export function UploadButton({ upload }: { upload: ReturnType<typeof useWavUpload> }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <input ref={input} type="file" accept=".wav,audio/wav" multiple hidden
        onChange={(e) => { if (e.target.files) void upload.send(e.target.files); e.target.value = ""; }} />
      <Button disabled={upload.busy} onClick={() => input.current?.click()}><Plus className="size-4" />{upload.busy ? "Uploading…" : "Analyse a call"}</Button>
      <span className="text-[11px] text-muted-foreground">.wav, or drop files anywhere on this page</span>
      {upload.msg && <span role="alert" className="max-w-xs text-xs text-alarm sm:text-right">{upload.msg}</span>}
    </div>
  );
}
