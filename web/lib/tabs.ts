// Tab definitions in one place (pattern from Leadership-Demo lib/tab-config.ts).
// Summary, evidence and the transcript are not tabs: they are always on the call page. "Details" holds the rest.
export const CALL_TABS = [
  { value: "reasoning", label: "Reasoning" },
  { value: "audio", label: "Audio analysis" },
  { value: "audit", label: "Audit" },
] as const;
export type TabValue = (typeof CALL_TABS)[number]["value"];
export const isTab = (v: string | undefined): v is TabValue => CALL_TABS.some((t) => t.value === v);

/** Display-only heuristic for dimming low-confidence ASR text. It does not feed any decision. */
export const ASR_LOW_LOGPROB = -0.45;
export const ASR_HIGH_NO_SPEECH = 0.25;
