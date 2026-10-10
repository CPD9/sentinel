"use client";
import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ApiError, uploadCall } from "@/lib/data";

/** Drag-and-drop of .wav files → POST /api/calls (one request per file). Adapted in spirit from Leadership-Demo's upload dropzone. */
export function UploadZone({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function send(files: FileList | File[]) {
    const list = Array.from(files);
    const wavs = list.filter((f) => f.name.toLowerCase().endsWith(".wav"));
    if (wavs.length !== list.length) setMsg("Only .wav files are accepted.");
    if (!wavs.length) return;
    setBusy(true);
    setMsg(null);
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
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); void send(e.dataTransfer.files); }}
      className={`flex flex-wrap items-center gap-3 rounded-lg border border-dashed px-4 py-3 text-sm ${drag ? "border-ring bg-info-bg" : "border-border"}`}
    >
      <Upload className="size-4" aria-hidden />
      <span className="text-muted-foreground">Drop .wav files here</span>
      <input ref={input} type="file" accept=".wav,audio/wav" multiple hidden onChange={(e) => e.target.files && void send(e.target.files)} />
      <Button variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>{busy ? "Uploading…" : "Choose files"}</Button>
      {msg && <span role="alert" className="text-xs text-alarm">{msg}</span>}
    </div>
  );
}
