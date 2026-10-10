"use client";
// STRETCH (docs/PRODUCT.md §7). Nothing depends on this; it renders only when feature_maps_status === "ok".
// Heat map rendering and the diverging scale follow audio-cnn FeatureMap.tsx / colors.ts (MIT, © 2025 Andreas Trolle).
import { divergingColor } from "@/lib/colors";
import { fmtRange } from "@/lib/format";
import type { AnalysisArtifact, FeatureLayer } from "@/lib/types";
import { DivergingColorBar } from "./color-bar";

export function FeatureMapsSection({ a }: { a: AnalysisArtifact }) {
  if (a.feature_maps_status !== "ok" || !a.feature_maps?.length) return null;
  return (
    <details className="rounded-lg border border-border bg-card p-4">
      <summary className="cursor-pointer text-sm font-semibold">Model internals (optional)</summary>
      <p className="mb-3 mt-1 text-xs text-muted-foreground">Selected layer activations for each evidence window. Explanatory only; they never feed the decision.</p>
      <div className="space-y-4">
        {a.feature_maps.map((w, i) => (
          <div key={i}>
            <h4 className="mb-1 text-xs font-semibold">Finding {w.finding_index + 1} · evidence {w.evidence_index + 1} · {fmtRange(w.start_s, w.end_s)}</h4>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{w.layers.map((l) => <Heat key={l.name} layer={l} />)}</div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex justify-end"><DivergingColorBar /></div>
    </details>
  );
}

function Heat({ layer }: { layer: FeatureLayer }) {
  const [rows, cols] = layer.shape;
  return (
    <figure>
      <svg viewBox={`0 0 ${cols} ${rows}`} preserveAspectRatio="none" className="h-24 w-full rounded border border-border" role="img" aria-label={`${layer.name} activations`}>
        {layer.values.flatMap((row, i) => row.map((v, j) => {
          const [r, g, b] = divergingColor(v);
          return <rect key={`${i}-${j}`} x={j} y={rows - 1 - i} width={1.02} height={1.02} fill={`rgb(${r},${g},${b})`} />;
        }))}
      </svg>
      <figcaption className="mt-1 text-[10px] text-muted-foreground">{layer.name} · {rows}×{cols} · {layer.pooling}</figcaption>
    </figure>
  );
}
