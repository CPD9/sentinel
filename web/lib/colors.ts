// Criterion / decision colours resolve to CSS variables (light + dark) defined in globals.css.
import type { Criterion } from "./types";

export const criterionColor = (c: string): string => `var(--c-${c in CRITERION_LABEL ? c : "other"})`;

export const CRITERION_LABEL: Record<Criterion, string> = {
  insider_trading: "Insider trading",
  credential_sharing: "Credential sharing",
  third_party_disclosure: "Third-party disclosure",
  documentation_concealment: "Documentation concealment",
  control_evasion: "Control evasion",
  payment_card_data: "Payment / card data",
  other: "Other",
};

export const SPEAKER_COLOR = { advisor: "var(--advisor)", customer: "var(--customer)", unknown: "var(--unknown)" } as const;

type RGB = [number, number, number];

/** Sequential map for dB spectrograms (inferno-like stops). t in [0, 1]. */
const SEQ: [number, RGB][] = [
  [0, [0, 0, 4]], [0.25, [87, 16, 110]], [0.5, [188, 55, 84]], [0.75, [249, 142, 9]], [1, [252, 255, 164]],
];
export function sequentialColor(t: number): RGB {
  const x = Math.min(1, Math.max(0, t));
  for (let i = 1; i < SEQ.length; i++) {
    const [t1, c1] = SEQ[i];
    if (x <= t1) {
      const [t0, c0] = SEQ[i - 1];
      const f = (x - t0) / (t1 - t0);
      return [0, 1, 2].map((k) => Math.round(c0[k] + (c1[k] - c0[k]) * f)) as RGB;
    }
  }
  return SEQ[SEQ.length - 1][1];
}
export const SEQ_GRADIENT = `linear-gradient(to top, ${SEQ.map(([t, c]) => `rgb(${c.join(",")}) ${t * 100}%`).join(", ")})`;

/**
 * Diverging orange ↔ white ↔ blue map for values in [-1, 1], centred on 0.
 * Adapted from audio-cnn (MIT, © 2025 Andreas Trolle), audio-cnn-visualisation/src/lib/colors.ts.
 */
export function divergingColor(value: number): RGB {
  const v = Math.max(-1, Math.min(1, value));
  if (v > 0) return [Math.round(255 * (1 - v * 0.8)), Math.round(255 * (1 - v * 0.5)), 255];
  return [255, Math.round(255 * (1 + v * 0.5)), Math.round(255 * (1 + v * 0.8))];
}
export const DIVERGING_GRADIENT = "linear-gradient(to right, rgb(255,128,51), rgb(255,255,255), rgb(51,128,255))";
