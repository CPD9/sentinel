// Legend for heatmaps. Layout idea adapted from audio-cnn ColorScale.tsx
// (MIT, © 2025 Andreas Trolle, https://github.com/Andreaswt/audio-cnn): min label, gradient bar, max label.
import { DIVERGING_GRADIENT, SEQ_GRADIENT } from "@/lib/colors";

/** Vertical bar for the dB spectrogram: top = max, bottom = min. Label and unit come from the data's `axes.value`. */
export function VerticalColorBar({ min, max, label, unit, height }: { min: number; max: number; label: string; unit: string; height: number }) {
  const ticks = [max, max - (max - min) / 2, min];
  return (
    <div className="flex items-stretch gap-1.5" style={{ height }} role="img" aria-label={`Colour scale ${label}, ${min} to ${max} ${unit}`}>
      <div className="w-3 rounded-sm border border-border" style={{ background: SEQ_GRADIENT }} />
      <div className="relative w-9 text-[10px] leading-none text-muted-foreground tabular">
        {ticks.map((v, i) => (
          <span key={i} className="absolute left-0" style={{ top: i === 0 ? 0 : i === 1 ? "50%" : undefined, bottom: i === 2 ? 0 : undefined, transform: i === 1 ? "translateY(-50%)" : undefined }}>{Math.round(v)}</span>
        ))}
        <span className="absolute -right-0.5 top-1/2 origin-center -translate-y-1/2 whitespace-nowrap" style={{ writingMode: "vertical-rl", transform: "translateY(-50%) rotate(180deg)", left: 20 }}>{label} ({unit})</span>
      </div>
    </div>
  );
}

/** Horizontal diverging legend for feature maps in [-1, 1] (centred on 0). */
export function DivergingColorBar({ min = -1, max = 1, width = 200 }: { min?: number; max?: number; width?: number }) {
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground tabular" role="img" aria-label={`Diverging colour scale ${min} to ${max}`}>
      <span>{min}</span>
      <div className="h-4 rounded border border-border" style={{ width, background: DIVERGING_GRADIENT }} />
      <span>{max}</span>
    </div>
  );
}
