// Hand-written mirror of pipeline/schemas.py (source of truth). Keep field names identical (snake_case).
// If schemas.py changes, update this file and docs/PRODUCT.md together.

export const DECISIONS = ["alarm", "review", "no_alert"] as const;
export type Decision = (typeof DECISIONS)[number];
export const SPEAKERS = ["advisor", "customer", "unknown"] as const;
export type Speaker = (typeof SPEAKERS)[number];
export type Mode = "reference" | "asr";

export const CRITERIA = [
  "insider_trading",
  "credential_sharing",
  "third_party_disclosure",
  "documentation_concealment",
  "control_evasion",
  "payment_card_data",
  "other",
] as const;
export type Criterion = (typeof CRITERIA)[number];

export const CRITERION_BY_FAMILY: Record<string, Criterion> = {
  trade: "insider_trading",
  access: "credential_sharing",
  disclosure: "third_party_disclosure",
  documentation: "documentation_concealment",
  splitting: "control_evasion",
  numbers: "payment_card_data",
};

export const STAGES = [
  "upload", "asr", "diarize", "keywords", "extract", "validate", "rules",
  "confidence", "decide", "narrate", "snippets", "analysis", "trigger",
] as const;
export type Stage = (typeof STAGES)[number];

export const VARIANTS = ["clean", "noisy", "unspecified"] as const;
export type Variant = (typeof VARIANTS)[number];
export const CALL_STATUSES = ["queued", "processing", "done", "error"] as const;
export type CallStatus = (typeof CALL_STATUSES)[number];
export const EVENT_TYPES = ["job_queued", "stage_started", "stage_finished", "stage_failed", "job_finished"] as const;
export type EventType = (typeof EVENT_TYPES)[number];

// ---- CallResult
export interface Evidence {
  segment_ids: string[];
  speaker: Speaker;
  text: string;
  start_s: number | null;
  end_s: number | null;
  snippet_path: string | null;
}
export interface Finding {
  criterion: Criterion;
  risk: number;
  reason: string;
  evidence: Evidence[];
  counter_evidence: Evidence[];
}
export interface StageError { stage: string; message: string }
export interface Versions { asr: string | null; llm: string | null; prompt: string | null; rules: string | null; provider: string | null; self_hosted: boolean | null }
export interface CallResult {
  call_id: string;
  decision: Decision;
  risk_score: number;
  confidence: number | null;
  findings: Finding[];
  narrative: string;
  stage_errors: StageError[];
  versions: Partial<Versions>;
}

// ---- Transcript
export interface TranscriptSegment {
  id: string;
  speaker: Speaker;
  text: string;
  start_s: number | null;
  end_s: number | null;
  avg_logprob: number | null;
  no_speech_prob: number | null;
  /** web-only, set by lib/use-speakers.ts: a second voice covers > 30 % of this segment */
  role_mixed?: boolean;
}
export interface Transcript {
  call_id: string;
  mode: Mode;
  segments: TranscriptSegment[];
  asr_model: string | null;
  duration_s: number | null;
  is_mock: boolean;
  notes: string[];
  /** web-only, set by lib/use-speakers.ts: where the displayed speaker roles come from */
  speaker_source?: string;
}

// ---- SpeakerRoles (display only, never feeds the decision; written by scripts/assign_speakers.py)
export interface SegmentRole { id: string; role: Speaker; cluster?: string | null; overlap_frac?: number | null; mixed?: boolean }
export interface SpeakerRoles {
  call_id: string;
  label_source: "acoustic + content" | "content only";
  diarizer: string | null;
  mapper: Record<string, string>;
  transcript: { path: string; asr_model: string; sha256: string };
  segments: SegmentRole[];
  cluster_roles: Record<string, Speaker>;
  rationale: string;
}

// ---- DecisionTrace
export type FactAct = "request" | "disclose" | "warn" | "refuse" | "hypothetical" | "quote" | "other";
export type InfoType = "credentials" | "nonpublic_info" | "client_data" | "other";
export const CONFIDENCE_COMPONENTS = ["asr", "threshold_proximity", "conflicts", "missing_evidence", "audio_quality"] as const;
export type DecisionPath =
  | "stage_error" | "missing_evidence" | "contradictory_evidence" | "low_confidence"
  | "alarm" | "review_band" | "no_alert";
export interface Fact {
  fact_id: string;
  speaker: Speaker;
  act: FactAct;
  info_type: InfoType;
  segment_ids: string[];
  quote: string;
  recipient_third_party: boolean | null;
  secrecy_cue: boolean | null;
  counter_evidence: string | null;
  valid: boolean;
  drop_reason: string | null;
  gloss_de?: string | null;            // the quote in Standard German (pipeline/schemas.py Fact.gloss_de)
}
export interface KeywordHit {
  hit_id: string;
  family: string;
  term: string;
  matched_text: string;
  segment_id: string;
  score: number;
}
export interface RuleResult {
  criterion: Criterion;
  risk: number;
  fired: boolean;
  reason: string;
  fact_ids: string[];
  keyword_hit_ids: string[];
}
export interface ConfidenceBreakdown { value: number; gate: number; components: Record<string, number> }
export interface Thresholds { alarm: number; review: number; confidence_gate: number }
export interface DecisionTrace {
  call_id: string;
  decision: Decision;
  decision_path: DecisionPath;
  risk_score: number;
  confidence: number | null;
  thresholds: Thresholds;
  facts: Fact[];
  keyword_hits: KeywordHit[];
  rules: RuleResult[];
  confidence_breakdown: ConfidenceBreakdown | null;
  why_not_flagged: string | null;
  what_would_change: string | null;
  timings_s: Record<string, number>;
  versions: Partial<Versions>;
  is_mock: boolean;
}

// ---- AnalysisArtifact
export interface Axis { label: string; unit: string }
export type Axes = Partial<Record<"x" | "y" | "value", Axis>>;
export interface Interval { start_s: number; end_s: number }
export interface EvidenceWindow extends Interval { criterion: Criterion; finding_index: number; evidence_index: number }
export interface WaveformPeaks { bucket_s: number; min: number[]; max: number[]; axes: Axes }
export interface MelSpectrogram {
  times_s: number[]; freqs_hz: number[]; db: number[][]; db_min: number; db_max: number; axes: Axes; png_path: string | null;
}
export interface SpeechActivity { intervals: Interval[]; axes: Axes }
export interface Turn extends Interval { speaker: Speaker; segment_ids: string[] }
export interface Turns { items: Turn[]; axes: Axes }
export interface RatePoint extends Interval { speaker: Speaker; value: number }
export interface SpeechRate { points: RatePoint[]; axes: Axes }
export interface Contour { times_s: number[]; values: (number | null)[]; axes: Axes }
export interface QualitySegment extends Interval { segment_id: string; snr_db: number; score: number }
export interface AudioQuality { call_snr_db: number; call_score: number; segments: QualitySegment[]; axes: Axes }
export interface AsrConfidencePoint extends Interval { segment_id: string; avg_logprob: number; no_speech_prob: number }
export interface AsrConfidence { segments: AsrConfidencePoint[]; axes: Axes }
export interface FeatureLayer { name: string; pooling: string; shape: number[]; values: number[][]; axes: Axes }
export interface FeatureMapWindow extends Interval { finding_index: number; evidence_index: number; layers: FeatureLayer[] }
export interface AnalysisArtifact {
  call_id: string;
  duration_s: number;
  sample_rate: number;
  evidence_windows: EvidenceWindow[];
  waveform_peaks: WaveformPeaks | null;
  mel_spectrogram: MelSpectrogram | null;
  speech_activity: SpeechActivity | null;
  turns: Turns | null;
  speech_rate: SpeechRate | null;
  pitch: Contour | null;
  energy: Contour | null;
  audio_quality: AudioQuality | null;
  asr_confidence: AsrConfidence | null;
  feature_maps: FeatureMapWindow[] | null; // STRETCH
  feature_maps_status: "not_computed" | "ok" | "error";
  stage_errors: StageError[];
  versions: { analysis: string | null; asr: string | null };
  is_mock: boolean;
}

// ---- Inbox + SSE
export interface CallListItem {
  call_id: string;
  status: CallStatus;
  duration_s: number | null;
  variant: Variant | null;
  decision: Decision | null;
  risk_score: number | null;
  confidence: number | null;
  criteria: Criterion[];
  n_stage_errors: number;
  updated_at: string | null;
  is_mock: boolean;
  decision_path?: DecisionPath | null;  // why the decision came out this way (from the trace); docs/API.md GET /calls
  reason?: string | null;               // the top finding's reason, one line
}
// ---- How each detection method decided (strategy comparison run, scripts/strategy_lab.py)
export interface MethodDecision { id: string; decision: Decision | null; risk: number | null; reason: string | null; criteria: string[]; error: boolean }
export interface MethodsResponse { call_id: string; run: string; default: string | null; top3: string[]; methods: MethodDecision[] }
export interface ReportResponse {
  call_id: string; dry_run: boolean;
  records: { mode: "dry-run" | "send"; payload: { url: string; title: string; description: string }; response?: unknown; error?: string }[];
  errors: string[];
}
export interface ProcessingEvent {
  seq: number;
  event: EventType;
  call_id: string;
  ts: string;
  stage: Stage | null;
  elapsed_s: number | null;
  cached: boolean | null;
  message: string | null;
  decision: Decision | null;
}

// ---- QualityReport
export interface Metric { value: number | null; ci_low: number | null; ci_high: number | null }
export interface BinaryMetrics { tp: number; fp: number; fn: number; tn: number; precision: Metric; recall: Metric; f1: Metric }
export interface ThreeClassMetrics {
  labels: Decision[];
  confusion: Record<string, Record<string, number>>; // rows = gold, columns = predicted
  macro_f1: Metric;
  accuracy: Metric;
}
export interface ConventionSet { n: number; strict_alarm: BinaryMetrics; escalation: BinaryMetrics; three_class: ThreeClassMetrics }
export interface Bootstrap { n_resamples: number; ci_level: number; unit: string; seed: number }
export interface CurvePoint { threshold: number; precision: number | null; recall: number | null; f1: number | null }
export interface ThresholdCurve {
  param: "alarm_threshold" | "review_threshold" | "confidence_gate";
  convention: "strict_alarm" | "escalation";
  current: number;
  points: CurvePoint[];
}
export interface ReliabilityBin { lo: number; hi: number; n: number; mean_confidence: number | null; accuracy: number | null }
export interface Reliability { correctness: string; bins: ReliabilityBin[]; ece: Metric }
export interface Ablation { name: "keyword_only" | "llm_only" | "combined"; transcript: Mode; conventions: ConventionSet }
export interface WerBin { wer_lo: number; wer_hi: number; n: number; escalation_recall: Metric }
export interface StageLatency { stage: Stage; n: number; mean_s: number; p50_s: number; p95_s: number }
export interface EvidenceValiditySummary {
  n_items: number; n_valid_items: number; item_validity_rate: number | null;
  per_check_pass_rate: Record<string, number>; checks_skipped: string[];
}
export interface QualityReport {
  report_id: string;
  created_at: string;
  run_id: string;
  system: string;
  provider: string;
  mode: Mode;
  split: "dev" | "holdout" | "test";
  bootstrap: Bootstrap;
  overall: ConventionSet;
  breakdowns: Record<string, Record<string, ConventionSet>>;
  threshold_curves: ThresholdCurve[];
  reliability: Reliability | null;
  ablations: Ablation[];
  wer_vs_recall: WerBin[];
  latency: StageLatency[];
  evidence_validity: EvidenceValiditySummary | null;
  warnings: string[];
  notes: string[];
  is_mock: boolean;
}
export interface QualityReportSummary {
  report_id: string; run_id: string; split: string; mode: string; system: string; created_at: string; is_mock: boolean;
}

// ---- Settings (proposals, docs/API.md)
export interface KeywordFamily { criterion: Criterion; terms: string[]; variants: Record<string, string[]>; label?: string }
export interface KeywordsConfig { families: Record<string, KeywordFamily>; fuzzy_threshold: number }
export interface RuleConfig { criterion: Criterion; enabled: boolean; [param: string]: unknown }
export interface RulesConfig { version: string; rules: RuleConfig[] }
export interface PreviewRequest { thresholds?: Thresholds; keywords?: KeywordsConfig; rules?: RulesConfig }
export interface PreviewResponse {
  decision_counts: { before: Record<string, number>; after: Record<string, number> };
  changed: { call_id: string; decision_before: Decision; decision_after: Decision; risk_before: number; risk_after: number }[];
  keyword_hit_counts: Record<string, Record<string, number>>;
  rule_fire_counts: Record<string, number>;
}
export interface RerunResponse { rerun: { stages: string[]; n_calls: number } }

// ---- What-if, feedback, suggestions (pipeline/schemas.py, docs/API.md "What-if, feedback and suggestions")
// escalate = "a person above me must look": recorded like any verdict, never changes a decision, not used by suggestions.
export const VERDICTS = ["false_alarm", "missed", "correct", "escalate"] as const;
export type Verdict = (typeof VERDICTS)[number];
export const DECISION_RANK: Record<Decision, number> = { no_alert: 0, review: 1, alarm: 2 };
/** A false alarm needs a flag to be false; a miss needs room above the current decision. */
export const verdictAllowed = (v: Verdict, d: Decision): boolean => !((v === "false_alarm" && d === "no_alert") || (v === "missed" && d === "alarm"));

export interface Patch {
  thresholds?: Partial<Thresholds>;
  keywords?: { disable_families: string[] } | KeywordsConfig;
  rules?: { disable: string[] } | RulesConfig;
}
export interface FeedbackEntry {
  call_id: string; verdict: Verdict; ts: string; decision_at_feedback: Decision;
  note: string | null; config_version: string | null; is_mock: boolean;
}
export interface Workload { n: number; alarms_per_100: number; reviews_per_100: number; flagged_per_100: number }
export interface FlippedCall {
  call_id: string; before: Decision; after: Decision; direction: "up" | "down";
  risk_before: number; risk_after: number; confidence_before: number | null; confidence_after: number | null;
  path_before: string; path_after: string; reasons: string[]; attributed_to: string[]; feedback_verdict: Verdict | null;
}
export interface FeedbackCheck { n_feedback: number; fix_credit: number; fixed: string[]; unchanged: string[]; violations: string[] }
export interface SimulationResult {
  patch: Patch; baseline_version: string; patched_version: string; n_calls: number; n_locked: number;
  counts: { before: Record<Decision, number>; after: Record<Decision, number> };
  workload: { before: Workload; after: Workload; delta_flagged_per_100: number };
  flipped: FlippedCall[]; feedback_check: FeedbackCheck | null; is_mock: boolean; schema_version: number;
}
export interface Suggestion {
  id: string; patch: Patch; title: string; rationale: string; config_version: string; n_knobs: number;
  fix_credit: number; fixed: string[]; not_fixed: string[]; collateral_flips: string[]; effect: SimulationResult;
}
export interface SuggestionsResponse {
  generated_at: string; config_version: string; n_feedback: number; counts_by_verdict: Partial<Record<Verdict, number>>;
  suggestions: Suggestion[]; caveat: string; reason: string | null; is_mock: boolean; schema_version: number;
}
export interface AuditEntry {
  ts: string; action: "apply_suggestion" | "settings_change"; patch: Patch; config_version_before: string;
  config_version_after: string; suggestion_id: string | null; note: string | null; n_flipped: number | null; is_mock: boolean;
}
export interface ApplyResponse { rerun: { stages: string[]; n_calls: number }; audit: AuditEntry }

// ---- Errors (docs/API.md)
export interface ApiErrorBody { error: string; detail: string | string[] }
