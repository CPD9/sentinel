// Officer-facing words for what the pipeline decided and why. Everything here is derived from real result / trace
// fields (pipeline/decide.py, rules.py, confidence.py); nothing is invented. API values stay as they are ("alarm"),
// only the labels change: one vocabulary everywhere, Alert / Review / No alert.
import { CRITERION_LABEL } from "./colors";
import type { ConfidenceBreakdown, Criterion, Decision, DecisionTrace, Fact, RuleResult, Speaker } from "./types";

export const DECISION_LABEL: Record<Decision, string> = { alarm: "Alert", review: "Review", no_alert: "No alert" };

/** The ONE place speaker names are made (hook for ml/speakers): Advisor / Customer when the role is known; a diarisation
 *  id ("spk_0", "speaker_1", "S1") becomes "Speaker 1, 2, …"; anything else is "Speaker". We never invent a person. */
export const speakerLabel = (s: Speaker | string | null | undefined) => {
  if (s === "advisor") return "Advisor";
  if (s === "customer") return "Customer";
  const v = String(s ?? "");
  const zeroBased = /^(?:spk|speaker)[_-]?(\d+)$/i.exec(v)?.[1];          // pyannote style: SPEAKER_00, spk_0
  if (zeroBased != null) return `Speaker ${Number(zeroBased) + 1}`;
  const oneBased = /^s(\d+)$/i.exec(v)?.[1];                               // S1, S2
  return oneBased != null ? `Speaker ${Number(oneBased)}` : "Speaker";
};

const ACT_VERB: Record<string, string> = {
  request: "asked for", disclose: "disclosed", warn: "warned about", refuse: "refused to give",
  hypothetical: "talked hypothetically about", quote: "quoted", other: "mentioned",
};
const INFO_NOUN: Record<string, string> = {
  credentials: "access credentials", nonpublic_info: "non-public information", client_data: "client data", other: "information",
};
export const actLabel = (a: string) => ACT_VERB[a] ?? a.replaceAll("_", " ");
export const infoLabel = (i: string) => INFO_NOUN[i] ?? i.replaceAll("_", " ");

/** "Customer disclosed access credentials" — one fact in plain words. */
export const factSentence = (f: Pick<Fact, "speaker" | "act" | "info_type" | "recipient_third_party" | "secrecy_cue">) => {
  const extra = [f.recipient_third_party ? "to a third party" : null, f.secrecy_cue ? "with a secrecy cue" : null].filter(Boolean).join(", ");
  return `${speakerLabel(f.speaker)} ${actLabel(f.act)} ${infoLabel(f.info_type)}${extra ? ` ${extra}` : ""}`;
};

/** The rule that carries the decision: the fired rule with the highest risk, else the highest-risk rule. */
export function topRule(t: DecisionTrace): RuleResult | null {
  const rules = [...t.rules].sort((a, b) => Number(b.fired) - Number(a.fired) || b.risk - a.risk);
  return rules[0] && rules[0].risk > 0 ? rules[0] : null;
}

/** One plain line for the inbox and the panel header: what the top rule saw, from its first valid fact. */
export function plainReason(t: DecisionTrace): string | null {
  const r = topRule(t);
  if (!r) return null;
  const facts = new Map(t.facts.map((f) => [f.fact_id, f]));
  const f = r.fact_ids.map((id) => facts.get(id)).find((x) => x && x.valid);
  const kind = CRITERION_LABEL[r.criterion as Criterion] ?? r.criterion;
  return f ? `${kind}: ${factSentence(f).toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}` : kind;
}

// Plain words for each confidence component (1 = no concern). The word cut-offs are a display choice, not pipeline thresholds.
export const COMPONENT_WORDS: Record<string, { label: string; low: string; ok: string; help: string }> = {
  asr: { label: "Transcript on the evidence", low: "unclear transcript", ok: "clear", help: "How sure speech recognition is on the cited passages." },
  audio_quality: { label: "Audio quality", low: "noisy audio", ok: "clear", help: "Signal-to-noise of the recording." },
  missing_evidence: { label: "Evidence verified", low: "evidence not verified", ok: "all cited evidence found in the transcript", help: "Facts whose quote or speaker could not be matched to the transcript are dropped." },
  conflicts: { label: "Facts agree with each other", low: "facts contradict each other", ok: "no contradictions", help: "Facts pointing in opposite directions lower confidence." },
  threshold_proximity: { label: "Distance to a line", low: "risk close to a line", ok: "clearly on one side", help: "A risk just above or below a line is less certain than one far from it." },
};
const LOW = 0.7;

/** Components below LOW, worst first, as officer words. */
export function concerns(cb: ConfidenceBreakdown | null): string[] {
  if (!cb) return [];
  return Object.entries(cb.components).filter(([, v]) => v < LOW).sort((a, b) => a[1] - b[1])
    .map(([k]) => COMPONENT_WORDS[k]?.low ?? k.replaceAll("_", " "));
}

const PATH_UNSURE: Record<string, string> = {
  stage_error: "a processing step failed",
  missing_evidence: "evidence not verified",
  contradictory_evidence: "methods disagree",
  low_confidence: "confidence below the gate",
  review_band: "risk between the review and alert line",
  judge_review: "the AI judge asks a person to look",
};
export const isJudgePath = (p: string | null | undefined) => !!p && p.startsWith("judge_");

/** "Unsure: risk between the review and alert line · noisy audio" — why a Review is a Review. */
export function unsureLine(t: DecisionTrace): string {
  const main = PATH_UNSURE[t.decision_path] ?? "not sure enough to decide alone";
  const extra = concerns(t.confidence_breakdown).filter((c) => c !== main && c !== "risk close to a line");
  return `Unsure: ${[main, ...extra].join(" · ")}`;
}

/** Which detection methods support a rule, from its inputs. Never inferred beyond fact_ids / keyword_hit_ids. */
export function methods(r: RuleResult, t: DecisionTrace) {
  const valid = new Set(t.facts.filter((f) => f.valid).map((f) => f.fact_id));
  const hitIds = new Set(t.keyword_hits.map((h) => h.hit_id));
  const facts = r.fact_ids.filter((id) => valid.has(id)).length;
  const keywords = r.keyword_hit_ids.filter((id) => hitIds.has(id)).length;
  return { facts, keywords, agree: facts > 0 && keywords > 0, factsOnly: facts > 0 && keywords === 0, keywordsOnly: keywords > 0 && facts === 0 };
}

/** Template narratives carry this prefix; we show them tagged, never as the reason. */
export const TEMPLATE_PREFIX = "[template narrative, no LLM]";
export const stripTemplate = (s: string | null | undefined) => {
  if (!s) return { text: null as string | null, template: false };
  const template = s.startsWith(TEMPLATE_PREFIX);
  return { text: template ? s.slice(TEMPLATE_PREFIX.length).trim() : s, template };
};

/** Pipeline wording → officer wording ("alarm threshold" → "alert line"). Used on trace texts written by the pipeline. */
export const officerWords = (s: string) =>
  s.replace(/\balarm threshold\b/gi, "alert line").replace(/\breview threshold\b/gi, "review line")
    .replace(/\bNot an alarm\b/g, "Not an alert").replace(/\balarm\b/g, "alert").replace(/\b(\d\.\d\d)\b/g, (m) => String(Math.round(parseFloat(m) * 100)));

/** 0–1 → "91" (risk and lines are shown as 0–100 numbers, never as "% fraud"). */
export const score = (x: number | null | undefined) => (x == null ? "–" : String(Math.round(x * 100)));

/** Officer names for the detection methods compared in the strategy lab (scripts/strategy_lab.py). */
export const METHOD_LABEL: Record<string, { name: string; how: string }> = {
  S1: { name: "Keywords only", how: "word lists, no AI" },
  S2: { name: "AI facts only", how: "facts + rules, no keywords" },
  S3: { name: "Hybrid (shipped)", how: "facts + keywords + rules" },
  S4: { name: "Direct AI judge", how: "one LLM verdict on the whole call" },
  S8: { name: "Majority vote", how: "S1 + S3 + S4; a split vote means review" },
};

/** The same "Unsure: …" line from the list row's decision_path alone (docs/API.md GET /calls), when no trace is loaded. */
export const unsureFromPath = (p: string | null | undefined) => (p && PATH_UNSURE[p] ? `Unsure: ${PATH_UNSURE[p]}` : null);

/** Steps that run after the decision is locked (CLAUDE.md steps 9-11 + analysis): their failure never changes the decision
 *  or removes its evidence. Only a failure that decided the call (decision_path "stage_error") blocks the reason. */
export const POST_DECISION_STAGES = new Set(["narrate", "snippets", "analysis", "trigger", "report"]);
export function blockingFailure(stageErrors: { stage: string }[], decisionPath: string | null | undefined): boolean {
  if (decisionPath) return decisionPath === "stage_error";
  return stageErrors.some((e) => !POST_DECISION_STAGES.has(e.stage.split(".")[0]));
}
