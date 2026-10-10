"use client";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { snippetUrl } from "@/lib/data";
import type { AnalysisArtifact } from "@/lib/types";

/** Snippet audio (cut passage ±10 s). 404 or a failed load → "snippet unavailable"; the card around it stays. */
export function SnippetPlayer({ callId, path, start, end, waveform }: {
  callId: string; path: string | null; start: number; end: number; waveform: AnalysisArtifact["waveform_peaks"] | null;
}) {
  const url = snippetUrl(callId, path);
  const [failed, setFailed] = useState(false);
  const lo = Math.max(0, start - 10), hi = end + 10;

  return (
    <div className="space-y-1.5">
      {waveform && <MiniWave peaks={waveform} lo={lo} hi={hi} hs={start} he={end} />}
      {url && !failed ? (
        <audio controls preload="none" src={url} className="h-9 w-full" onError={() => setFailed(true)} />
      ) : (
        <p className="flex items-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
          <AlertCircle className="size-3.5" />snippet unavailable{!url ? " (no audio in fixtures mode)" : ""}
        </p>
      )}
    </div>
  );
}

/** Tiny waveform of the ±10 s window with the cited passage highlighted. */
function MiniWave({ peaks, lo, hi, hs, he }: { peaks: NonNullable<AnalysisArtifact["waveform_peaks"]>; lo: number; hi: number; hs: number; he: number }) {
  const W = 400, H = 36;
  const b0 = Math.max(0, Math.floor(lo / peaks.bucket_s));
  const b1 = Math.min(peaks.min.length, Math.ceil(hi / peaks.bucket_s));
  const n = Math.max(1, b1 - b0);
  const x = (t: number) => ((t - lo) / (hi - lo)) * W;
  let d = "";
  for (let i = b0; i < b1; i++) {
    const px = ((i - b0) / n) * W;
    d += `M${px.toFixed(1)} ${(H / 2 - peaks.max[i] * (H / 2)).toFixed(1)}V${(H / 2 - peaks.min[i] * (H / 2)).toFixed(1)}`;
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-9 w-full rounded border border-border bg-[var(--lane-bg)]" preserveAspectRatio="none" role="img" aria-label={`Waveform ${lo.toFixed(0)}–${hi.toFixed(0)} s, cited passage highlighted`}>
      <rect x={x(hs)} width={Math.max(2, x(he) - x(hs))} y={0} height={H} fill="var(--info)" opacity={0.2} />
      <path d={d} stroke="var(--trace)" strokeWidth={1} opacity={0.8} />
    </svg>
  );
}
