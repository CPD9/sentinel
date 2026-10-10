// The ONLY module that fetches. Every UI surface goes through here.
//   NEXT_PUBLIC_DATA_MODE=fixtures  → reads public/fixtures/*.json (copied from ../fixtures; MOCK data)
//   NEXT_PUBLIC_DATA_MODE=api       → follows docs/API.md exactly, via the same-origin /api proxy (next.config.ts)
import { replayDelayMs, synthFinishedEvents, synthRunningEvents } from "./mock-replay";
import { approxSimulate, patchComponents, samePatch, type WhatifCalls } from "./whatif-mock";
import type {
  AnalysisArtifact, ApiErrorBody, ApplyResponse, AuditEntry, CallListItem, CallResult, DecisionTrace, FeedbackEntry,
  Decision, KeywordsConfig, Patch, PreviewRequest, PreviewResponse, ProcessingEvent, QualityReport, QualityReportSummary,
  RerunResponse, RulesConfig, SimulationResult, SuggestionsResponse, Thresholds, Transcript, Verdict,
} from "./types";
import { CRITERIA, EVENT_TYPES, verdictAllowed } from "./types";

export const DATA_MODE: "fixtures" | "api" = process.env.NEXT_PUBLIC_DATA_MODE === "api" ? "api" : "fixtures";
export const isFixtures = DATA_MODE === "fixtures";

export class ApiError extends Error {
  constructor(public status: number, public code: string, public detail: string | string[]) {
    super(Array.isArray(detail) ? detail.join("; ") : detail);
  }
  get notAvailable() { return this.status === 404; }
}

// ------------------------------------------------------------------ transport
async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as Partial<ApiErrorBody>;
    return new ApiError(res.status, body.error ?? "internal", body.detail ?? res.statusText);
  } catch {
    return new ApiError(res.status, res.status === 404 ? "not_found" : "internal", res.statusText || `HTTP ${res.status}`);
  }
}

async function getJson<T>(url: string): Promise<{ status: number; data: T }> {
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (e) {
    throw new ApiError(0, "unreachable", `Cannot reach ${url}: ${(e as Error).message}`);
  }
  if (res.status === 404) throw await parseError(res);
  if (!res.ok && res.status !== 202) throw await parseError(res);
  return { status: res.status, data: (await res.json()) as T };
}

const fx = (name: string) => `/fixtures/${name}`;
const api = (path: string) => `/api${path}`;
const unsupported = (what: string) =>
  new ApiError(409, "conflict", `${what} is disabled in fixtures mode (MOCK data only, as in API.md "Fixture mode").`);

function notAvailable(what: string) {
  return new ApiError(404, "not_available", `${what} not available`);
}

// ------------------------------------------------------------------ calls
export async function getCalls(): Promise<CallListItem[]> {
  return (await getJson<CallListItem[]>(isFixtures ? fx("calls.json") : api("/calls"))).data;
}

export type CallDetail = { kind: "result"; data: CallResult } | { kind: "pending"; item: CallListItem };

export async function getCall(id: string): Promise<CallDetail> {
  if (isFixtures) {
    try {
      return { kind: "result", data: (await getJson<CallResult>(fx(`${id}.result.json`))).data };
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 404) throw e;
      const row = (await getCalls()).find((c) => c.call_id === id);
      if (!row) throw new ApiError(404, "not_found", `Unknown call ${id}`);
      if (row.status === "queued" || row.status === "processing") return { kind: "pending", item: row };
      throw notAvailable("Result");
    }
  }
  const { status, data } = await getJson<CallResult | CallListItem>(api(`/calls/${id}`));
  return status === 202 ? { kind: "pending", item: data as CallListItem } : { kind: "result", data: data as CallResult };
}

export async function getTranscript(id: string): Promise<Transcript> {
  return (await getJson<Transcript>(isFixtures ? fx(`${id}.transcript.json`) : api(`/calls/${id}/transcript`))).data;
}
export async function getTrace(id: string): Promise<DecisionTrace> {
  return (await getJson<DecisionTrace>(isFixtures ? fx(`${id}.trace.json`) : api(`/calls/${id}/trace`))).data;
}
export async function getAnalysis(id: string): Promise<AnalysisArtifact> {
  return (await getJson<AnalysisArtifact>(isFixtures ? fx(`${id}.analysis.json`) : api(`/calls/${id}/analysis`))).data;
}

/** Audio URLs. In fixtures mode there is no audio (*.wav is gitignored): callers get null and show the 404 state. */
export const audioUrl = (id: string): string | null => (isFixtures ? null : api(`/calls/${id}/audio`));
export function snippetUrl(id: string, snippetPath: string | null): string | null {
  if (isFixtures || !snippetPath) return null;
  const name = snippetPath.split("/").pop() ?? "";
  return api(`/calls/${id}/snippets/${encodeURIComponent(name)}`);
}

export async function uploadCall(file: File, variant?: string): Promise<CallListItem> {
  if (isFixtures) throw unsupported("Upload");
  const form = new FormData();
  form.append("file", file);
  if (variant) form.append("variant", variant);
  const res = await fetch(api("/calls"), { method: "POST", body: form });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as CallListItem;
}

// ------------------------------------------------------------------ events (SSE)
export type StreamStatus = "connecting" | "open" | "reconnecting" | "failed" | "closed";
export interface Subscription { close(): void }

/** Per-call events: past events are replayed first, then live. Closes after job_finished. */
export function subscribeCallEvents(
  id: string,
  onEvent: (e: ProcessingEvent) => void,
  onStatus: (s: StreamStatus) => void,
): Subscription {
  return isFixtures ? mockReplay(id, onEvent, onStatus) : sse(api(`/calls/${id}/events`), onEvent, onStatus, true);
}

/** Global stream for the Inbox. Live only. Nothing arrives in fixtures mode. */
export function subscribeGlobalEvents(onEvent: (e: ProcessingEvent) => void, onStatus: (s: StreamStatus) => void): Subscription {
  if (isFixtures) { onStatus("closed"); return { close() {} }; }
  return sse(api("/events"), onEvent, onStatus, false);
}

function sse(url: string, onEvent: (e: ProcessingEvent) => void, onStatus: (s: StreamStatus) => void, closeOnFinish: boolean): Subscription {
  // The browser resumes with Last-Event-ID by itself on reconnect (API.md).
  const es = new EventSource(url);
  let failures = 0;
  onStatus("connecting");
  es.onopen = () => { failures = 0; onStatus("open"); };
  es.onerror = () => {
    failures += 1;
    if (failures >= 3) { es.close(); onStatus("failed"); } else onStatus("reconnecting");
  };
  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (m) => {
      const ev = JSON.parse((m as MessageEvent).data) as ProcessingEvent;
      onEvent(ev);
      if (closeOnFinish && type === "job_finished") { es.close(); onStatus("closed"); }
    });
  }
  return { close: () => es.close() };
}

function mockReplay(id: string, onEvent: (e: ProcessingEvent) => void, onStatus: (s: StreamStatus) => void): Subscription {
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  onStatus("connecting");
  (async () => {
    let events: ProcessingEvent[];
    try {
      events = (await getJson<ProcessingEvent[]>(fx(`${id}.events.json`))).data;
    } catch {
      const detail = await getCall(id).catch(() => null);
      if (!detail) events = [];
      else if (detail.kind === "pending") events = synthRunningEvents(id);
      else {
        const trace = await getTrace(id).catch(() => null);
        events = synthFinishedEvents(id, detail.data, trace);
      }
    }
    if (cancelled) return;
    onStatus("open");
    let prev: ProcessingEvent | null = null;
    let i = 0;
    const step = () => {
      if (cancelled) return;
      const ev = events[i];
      if (!ev) { onStatus(events.at(-1)?.event === "job_finished" ? "closed" : "open"); return; }
      onEvent(ev);
      prev = ev;
      i += 1;
      const next = events[i];
      if (next) timer = setTimeout(step, replayDelayMs(prev, next));
      else onStatus(ev.event === "job_finished" ? "closed" : "open");
    };
    timer = setTimeout(step, replayDelayMs(null, events[0] ?? ({ ts: "" } as ProcessingEvent)));
  })();
  return { close: () => { cancelled = true; if (timer) clearTimeout(timer); } };
}

// ------------------------------------------------------------------ quality
export async function getQualityReports(): Promise<QualityReportSummary[]> {
  if (isFixtures) {
    const r = (await getJson<QualityReport>(fx("quality_report.json"))).data;
    return [{ report_id: r.report_id, run_id: r.run_id, split: r.split, mode: r.mode, system: r.system, created_at: r.created_at, is_mock: r.is_mock }];
  }
  return (await getJson<QualityReportSummary[]>(api("/quality"))).data;
}
export async function getQualityReport(reportId: string): Promise<QualityReport> {
  if (isFixtures) {
    const r = (await getJson<QualityReport>(fx("quality_report.json"))).data;
    if (r.report_id !== reportId) throw new ApiError(404, "not_found", `Unknown report ${reportId}`);
    return r;
  }
  return (await getJson<QualityReport>(api(`/quality/${reportId}`))).data;
}

// ------------------------------------------------------------------ settings
// Fixtures mode has no settings files (PRODUCT.md §8). Defaults below are MOCK and edits are not persisted
// across reloads; the preview is a client-side approximation over the two traced fixture calls.
const MOCK_THRESHOLDS: Thresholds = { alarm: 0.7, review: 0.4, confidence_gate: 0.5 };
const MOCK_KEYWORDS: KeywordsConfig = {
  fuzzy_threshold: 0.85,
  families: {
    access: { criterion: "credential_sharing", terms: ["Passwort", "PIN", "Zugangscode"], variants: { Passwort: ["Passwörter", "Passwoort"], PIN: ["Pin-Code"] } },
    trade: { criterion: "insider_trading", terms: ["Aktie", "Kauforder"], variants: { Aktie: ["Aktie", "Aktiä"] } },
    disclosure: { criterion: "third_party_disclosure", terms: ["Kontostand", "Vermögen"], variants: {} },
    documentation: { criterion: "documentation_concealment", terms: ["nöd notiere", "nicht protokollieren"], variants: {} },
    splitting: { criterion: "control_evasion", terms: ["aufteile", "Teilbeträge"], variants: {} },
    numbers: { criterion: "payment_card_data", terms: ["Kartenummer", "IBAN"], variants: {} },
  },
};
const MOCK_RULES: RulesConfig = { version: "MOCK", rules: CRITERIA.filter((c) => c !== "other").map((criterion) => ({ criterion, enabled: true })) };

export async function getThresholds(): Promise<Thresholds> {
  if (isFixtures) {
    const t = await getTrace("call_MOCK_001").catch(() => null);
    return t?.thresholds ?? MOCK_THRESHOLDS;
  }
  return (await getJson<Thresholds>(api("/settings/thresholds"))).data;
}
export async function getKeywords(): Promise<KeywordsConfig> {
  return isFixtures ? structuredClone(MOCK_KEYWORDS) : (await getJson<KeywordsConfig>(api("/settings/keywords"))).data;
}
export async function getRules(): Promise<RulesConfig> {
  return isFixtures ? structuredClone(MOCK_RULES) : (await getJson<RulesConfig>(api("/settings/rules"))).data;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  if (isFixtures) throw unsupported("Saving settings");
  const res = await fetch(api(path), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}
export const putThresholds = (t: Thresholds) => put<RerunResponse>("/settings/thresholds", t);
export const putKeywords = (k: KeywordsConfig) => put<RerunResponse>("/settings/keywords", k);
export const putRules = (r: RulesConfig) => put<RerunResponse>("/settings/rules", r);

export async function previewSettings(req: PreviewRequest): Promise<PreviewResponse> {
  if (!isFixtures) {
    const res = await fetch(api("/settings/preview"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
    if (!res.ok) throw await parseError(res);
    return (await res.json()) as PreviewResponse;
  }
  return mockPreview(req);
}

/** MOCK approximation of POST /settings/preview. Mirrors decide.py priority only roughly. */
async function mockPreview(req: PreviewRequest): Promise<PreviewResponse> {
  const rows = await getCalls();
  const base = await getThresholds();
  const next = req.thresholds ?? base;
  const traces = new Map<string, DecisionTrace>();
  const transcripts = new Map<string, Transcript>();
  await Promise.all(rows.map(async (r) => {
    const [t, tr] = await Promise.all([getTrace(r.call_id).catch(() => null), getTranscript(r.call_id).catch(() => null)]);
    if (t) traces.set(r.call_id, t);
    if (tr) transcripts.set(r.call_id, tr);
  }));
  const decide = (row: CallListItem, th: Thresholds) => {
    if (row.decision == null || row.risk_score == null) return null;
    const tr = traces.get(row.call_id);
    const forced = row.n_stage_errors > 0 || (tr && ["stage_error", "missing_evidence", "contradictory_evidence"].includes(tr.decision_path));
    if (forced || row.confidence == null || row.confidence < th.confidence_gate) return "review" as const;
    if (row.risk_score >= th.alarm) return "alarm" as const;
    if (row.risk_score >= th.review) return "review" as const;
    return "no_alert" as const;
  };
  const counts = (th: Thresholds) => {
    const c: Record<string, number> = { alarm: 0, review: 0, no_alert: 0 };
    for (const r of rows) { const d = decide(r, th); if (d) c[d] += 1; }
    return c;
  };
  const changed = rows.flatMap((r) => {
    const before = decide(r, base), after = decide(r, next);
    return before && after && before !== after
      ? [{ call_id: r.call_id, decision_before: before, decision_after: after, risk_before: r.risk_score ?? 0, risk_after: r.risk_score ?? 0 }]
      : [];
  });
  const kw = req.keywords ?? MOCK_KEYWORDS;
  const keyword_hit_counts: PreviewResponse["keyword_hit_counts"] = {};
  for (const [family, f] of Object.entries(kw.families)) {
    keyword_hit_counts[family] = {};
    for (const term of [...f.terms, ...Object.values(f.variants).flat()]) {
      const needle = term.toLowerCase();
      let n = 0;
      for (const tr of transcripts.values()) n += tr.segments.filter((s) => s.text.toLowerCase().includes(needle)).length;
      keyword_hit_counts[family][term] = n;
    }
  }
  const rule_fire_counts: Record<string, number> = {};
  for (const tr of traces.values()) for (const rule of tr.rules) {
    rule_fire_counts[rule.criterion] = (rule_fire_counts[rule.criterion] ?? 0) + (rule.risk >= next.review ? 1 : 0);
  }
  return { decision_counts: { before: counts(base), after: counts(next) }, changed, keyword_hit_counts, rule_fire_counts };
}

// ------------------------------------------------------------------ what-if, feedback, suggestions
// API mode follows docs/API.md "What-if, feedback and suggestions". Fixtures mode (MOCK): feedback lives in this browser only,
// suggestions are the stored sample from fixtures/suggestions.json, and a hand-made draft is simulated by whatif-mock.ts.
const LS_FEEDBACK = "sentinel.mock.feedback.v1";
let memoryFeedback: FeedbackEntry[] | null = null;

function localFeedback(): FeedbackEntry[] {
  if (memoryFeedback) return memoryFeedback;
  try { memoryFeedback = JSON.parse(localStorage.getItem(LS_FEEDBACK) ?? "[]") as FeedbackEntry[]; } catch { memoryFeedback = []; }
  return memoryFeedback;
}
function persistFeedback() {
  try { localStorage.setItem(LS_FEEDBACK, JSON.stringify(memoryFeedback ?? [])); } catch { /* private window: memory only */ }
}

/** The checked-in API may not have the what-if routes yet (docs/API.md "What-if, feedback and suggestions"): 404/405 means "not built". */
const routeMissing = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 405);
const notBuilt = (what: string, route: string) => new ApiError(404, "not_available", `${what}: not available on this server yet (${route} is not implemented).`);

/** Latest verdict per call. Throws not_available when the server has no feedback route. */
export async function getFeedback(): Promise<FeedbackEntry[]> {
  if (!isFixtures) {
    try { return (await getJson<FeedbackEntry[]>(api("/feedback"))).data; }
    catch (e) { throw routeMissing(e) ? notBuilt("Officer feedback", "GET /api/feedback") : e; }
  }
  const base = (await getJson<FeedbackEntry[]>(fx("feedback.json"))).data;
  const latest = new Map<string, FeedbackEntry>();
  for (const e of [...base, ...localFeedback()]) latest.set(e.call_id, e);
  return [...latest.values()];
}

export async function postFeedback(callId: string, verdict: Verdict, note?: string): Promise<FeedbackEntry> {
  if (!isFixtures) {
    const res = await fetch(api("/feedback"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ call_id: callId, verdict, note: note || undefined }) });
    if (!res.ok) { const e = await parseError(res); throw e.status === 405 ? notBuilt("Officer feedback", "POST /api/feedback") : e; }
    return (await res.json()) as FeedbackEntry;
  }
  const row = (await getCalls()).find((c) => c.call_id === callId);
  const decision = row?.decision ?? (await getJson<WhatifCalls>(fx("whatif_calls.json"))).data.calls.find((c) => c.call_id === callId)?.decision;
  if (!decision) throw new ApiError(404, "not_found", `Unknown call ${callId} (or it has no decision yet)`);
  if (!verdictAllowed(verdict, decision)) throw new ApiError(422, "invalid", `${verdict.replace("_", " ")} makes no sense for a ${decision} call`);
  const entry: FeedbackEntry = { call_id: callId, verdict, ts: new Date().toISOString().replace(/\.\d+Z$/, "Z"), decision_at_feedback: decision, note: note?.trim() || null, config_version: null, is_mock: true };
  localFeedback().push(entry);
  persistFeedback();
  return entry;
}

let simulateMissing = false;                       // remembered after the first 404/405, so a drag does not retry a missing route

export async function simulate(patch: Patch): Promise<SimulationResult> {
  if (!isFixtures) {
    if (!simulateMissing) {
      const res = await fetch(api("/simulate"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ patch, with_feedback: true }) });
      if (res.ok) return (await res.json()) as SimulationResult;
      const err = await parseError(res);
      if (!routeMissing(err)) throw err;
      simulateMissing = true;
    }
    return simulateViaPreview(patch);
  }
  const [data, sugg, fb] = await Promise.all([
    getJson<WhatifCalls>(fx("whatif_calls.json")).then((r) => r.data),
    getSuggestions(), getFeedback(),
  ]);
  const exact = sugg.suggestions.find((s) => samePatch(s.patch, patch));
  if (exact) return exact.effect;                                        // stored real simulate() result
  return approxSimulate(patch, data, new Map(fb.map((f) => [f.call_id, f])));
}

/** Fallback while the server has no POST /simulate: the existing POST /settings/preview, mapped to the simulation shape.
 *  It has no reasons, no workload from the server and no feedback check; the impact panel says so (baseline_version "unknown"). */
async function simulateViaPreview(patch: Patch): Promise<SimulationResult> {
  const req: PreviewRequest = {};
  if (patch.thresholds && Object.keys(patch.thresholds).length) req.thresholds = { ...(await getThresholds()), ...patch.thresholds };
  if (patch.keywords) {
    if ("families" in patch.keywords) req.keywords = patch.keywords;
    else if (patch.keywords.disable_families.length) {
      const k = await getKeywords();
      for (const f of patch.keywords.disable_families) delete k.families[f];
      req.keywords = k;
    }
  }
  if (patch.rules) {
    if ("rules" in patch.rules) req.rules = patch.rules;
    else if (patch.rules.disable.length) {
      const off = patch.rules.disable;
      const r = await getRules();
      for (const x of r.rules) if (off.includes(x.criterion)) x.enabled = false;
      req.rules = r;
    }
  }
  const p = await previewSettings(req);
  const full = (c: Record<string, number>) => ({ alarm: c.alarm ?? 0, review: c.review ?? 0, no_alert: c.no_alert ?? 0 }) as Record<Decision, number>;
  const before = full(p.decision_counts.before), after = full(p.decision_counts.after);
  const load = (c: Record<Decision, number>) => {
    const n = c.alarm + c.review + c.no_alert, per = (x: number) => (n ? Math.round((10000 * x) / n) / 100 : 0);
    return { n, alarms_per_100: per(c.alarm), reviews_per_100: per(c.review), flagged_per_100: per(c.alarm + c.review) };
  };
  const wb = load(before), wa = load(after);
  const rank = { no_alert: 0, review: 1, alarm: 2 } as const;
  return {
    patch, baseline_version: "unknown", patched_version: "draft", n_calls: wa.n, n_locked: 0,
    counts: { before, after },
    workload: { before: wb, after: wa, delta_flagged_per_100: Math.round((wa.flagged_per_100 - wb.flagged_per_100) * 100) / 100 },
    flipped: p.changed.map((c) => ({
      call_id: c.call_id, before: c.decision_before, after: c.decision_after,
      direction: (rank[c.decision_after] > rank[c.decision_before] ? "up" : "down") as "up" | "down",
      risk_before: c.risk_before, risk_after: c.risk_after, confidence_before: null, confidence_after: null,
      path_before: "n/a", path_after: "n/a", reasons: [], attributed_to: patchComponents(patch), feedback_verdict: null,
    })),
    feedback_check: null, is_mock: false, schema_version: 1,
  };
}

export async function getSuggestions(max = 5): Promise<SuggestionsResponse> {
  if (isFixtures) return (await getJson<SuggestionsResponse>(fx("suggestions.json"))).data;
  try { return (await getJson<SuggestionsResponse>(api(`/suggestions?max=${max}`))).data; }
  catch (e) { throw routeMissing(e) ? notBuilt("Suggestions", "GET /api/suggestions") : e; }
}

export async function applySuggestion(id: string, note?: string): Promise<ApplyResponse> {
  if (isFixtures) throw unsupported("Applying a suggestion");
  const res = await fetch(api(`/suggestions/${encodeURIComponent(id)}/apply`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true, note: note || undefined }) });
  if (!res.ok) { const e = await parseError(res); throw e.status === 405 ? notBuilt("Applying a suggestion", "POST /api/suggestions/{id}/apply") : e; }
  return (await res.json()) as ApplyResponse;
}

export async function getAudit(): Promise<AuditEntry[]> {
  if (isFixtures) return [];
  try { return (await getJson<AuditEntry[]>(api("/audit"))).data; }
  catch (e) { if (routeMissing(e)) return []; throw e; }          // no audit route yet: nothing to list, not an error
}

/** Saves a toggle-style draft through the existing PUT /settings/* endpoints (thresholds, then keyword families, then rules). */
export async function saveDraft(patch: Patch): Promise<RerunResponse> {
  if (isFixtures) throw unsupported("Saving settings");
  let last: RerunResponse | null = null;
  if (patch.thresholds && Object.keys(patch.thresholds).length) last = await putThresholds({ ...(await getThresholds()), ...patch.thresholds });
  const fams = patch.keywords && "disable_families" in patch.keywords ? patch.keywords.disable_families : [];
  if (fams.length) { const k = await getKeywords(); for (const f of fams) delete k.families[f]; last = await putKeywords(k); }
  const off = patch.rules && "disable" in patch.rules ? patch.rules.disable : [];
  if (off.length) { const r = await getRules(); for (const x of r.rules) if (off.includes(x.criterion)) x.enabled = false; last = await putRules(r); }
  if (!last) throw new ApiError(422, "invalid", "Nothing to save");
  return last;
}
