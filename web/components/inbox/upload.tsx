"use client";
import { Plus } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ApiError, isFixtures, isLocalRun, liveUpload, uploadCall } from "@/lib/data";

/** Upload of .wav files → POST /api/calls (one request per file). One file opens its live processing view. */
export function useWavUpload(onUploaded: () => void) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const send = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files);
    const wavs = list.filter((f) => f.name.toLowerCase().endsWith(".wav")).slice(0, 1);      // one call at a time
    setMsg(list.length > 1 ? "One file at a time: the first .wav is analysed." : wavs.length === 0 ? "Only .wav files are accepted." : null);
    if (!wavs.length) return;
    setBusy(true);
    try {
      let last: string | null = null;
      for (const f of wavs) last = (await uploadCall(f)).call_id;
      onUploaded();
      if (last) router.push(`/calls/${last}/processing`);
    } catch (e) {
      setMsg(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  }, [onUploaded, router]);

  return { send, busy, msg };
}

/** "Analyse a call" button. In production calls arrive automatically; this is the manual path for the demo. */
export function UploadButton({ upload, label = "Analyse a call" }: { upload: ReturnType<typeof useWavUpload>; label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  // never a dead control: hidden where uploading cannot work (fixtures, a read-only run without the live path)
  if (isFixtures || (isLocalRun && !liveUpload)) return null;
  return (
    <div className="flex flex-col items-end gap-1">
      <input ref={input} type="file" accept=".wav,audio/wav" multiple hidden
        onChange={(e) => { if (e.target.files) void upload.send(e.target.files); e.target.value = ""; }} />
      <Button variant="outline" size="sm" className="rounded-full" disabled={upload.busy} onClick={() => input.current?.click()}
        title="One .wav (up to 50 MB): transcribed and checked live, about a minute per call"><Plus className="size-4" />{upload.busy ? "Uploading…" : label}</Button>
      {upload.msg && <span role="alert" className="max-w-xs text-xs text-alarm sm:text-right">{upload.msg}</span>}
    </div>
  );
}
