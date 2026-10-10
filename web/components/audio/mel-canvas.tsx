"use client";
// Mel spectrogram heat map on a canvas (277+ columns x 40+ rows would be thousands of SVG nodes).
// Idea (one rect per cell, colour from value) adapted from audio-cnn FeatureMap.tsx (MIT, © 2025 Andreas Trolle);
// the colour range is the data's own db_min..db_max, so colours are comparable across calls.
import { useEffect, useRef } from "react";
import { sequentialColor } from "@/lib/colors";
import type { MelSpectrogram } from "@/lib/types";
import type { Scale } from "./lane-frame";
import { xOf } from "./lane-frame";

export function MelCanvas({ mel, scale, height }: { mel: MelSpectrogram; scale: Scale; height: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(scale.w * dpr);
    c.height = Math.round(height * dpr);
    const g = c.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, scale.w, height);
    const { times_s: ts, db, db_min, db_max } = mel;
    const rows = db.length;
    const rowH = height / rows;
    const range = db_max - db_min || 1;
    for (let j = 0; j < ts.length; j++) {
      const dt = j < ts.length - 1 ? ts[j + 1] - ts[j] : ts[j] - ts[j - 1] || 0.1;
      const t0 = ts[j] - dt / 2, t1 = ts[j] + dt / 2;
      if (t1 < scale.t0 || t0 > scale.t1) continue;
      const x0 = Math.floor(xOf(scale, t0)), x1 = Math.ceil(xOf(scale, t1));
      for (let i = 0; i < rows; i++) {
        const [r, gg, b] = sequentialColor((db[i][j] - db_min) / range);
        g.fillStyle = `rgb(${r},${gg},${b})`;
        // row 0 = lowest mel band → bottom of the lane
        g.fillRect(x0, height - (i + 1) * rowH, Math.max(1, x1 - x0), Math.ceil(rowH) + 0.5);
      }
    }
  }, [mel, scale, height]);
  return <canvas ref={ref} style={{ width: scale.w, height }} className="block rounded-sm border border-border" role="img" aria-label="Mel spectrogram" />;
}
