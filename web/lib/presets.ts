// Sensitivity presets: they only move the alert line (review line and confidence gate stay as configured).
// Shared by Settings → Threshold and the impact meter on the Overview, so both show the same three choices.
export const PRESETS = [
  { label: "Cautious", alarm: 0.5, hint: "catches more, more calls for a person" },
  { label: "Balanced", alarm: 0.7, hint: "the shipped default" },
  { label: "Strict", alarm: 0.85, hint: "fewer false alarms, may miss weaker cases" },
];
