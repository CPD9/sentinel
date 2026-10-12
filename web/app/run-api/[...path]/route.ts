// LOCAL-RUN FALLBACK, read-only. Serves one finished pipeline run in the shapes of docs/API.md, for as long as the
// FastAPI service has no real mode. Enabled only when the web app runs with NEXT_PUBLIC_API_PREFIX=/run-api and
// SENTINEL_RUN_DIR (the run's out/ folder) + SENTINEL_ARTIFACTS_DIR (its artifacts/ folder) are set. Swapping in a
// new run = pointing the two variables at it.
//   reads    results/*.json (+ results.json), transcripts[_reference]/, traces[_reference]/, analysis/<id>/analysis.json,
//            audio/<id>.wav (Range requests), out/snippets/<id>/, artifacts/manifests/inference.json (variant only:
//            neutral ids, never evaluation.json), artifacts/quality/final_report.json, config/*.json of the repo,
//            <SENTINEL_SPEAKERS_DIR or RUN/../speakers>/<id>.json (display-only speaker roles, scripts/assign_speakers.py),
//            <SENTINEL_DIALECT_DIR or RUN/../dialect>/<id>.json (display-only language routing, scripts/dialect_map.py)
//   what-if  POST /simulate runs pipeline/simulate.py (exact decide.py over the cached facts) in a helper process
//   writes   nothing on disk. Feedback lives in this server's memory until restart; saving settings is refused (409).
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createReadStream, existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { createInterface } from "node:readline";
import { eventStream, isUploadId, runningJob, startUpload, uploadPaths, uploadRows } from "../uploads";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RUN = process.env.SENTINEL_RUN_DIR ?? "";
const ART = process.env.SENTINEL_ARTIFACTS_DIR ?? "";
const REPO = path.resolve(process.cwd(), "..");
const SPK = process.env.SENTINEL_SPEAKERS_DIR ?? (RUN ? path.join(RUN, "..", "speakers") : "");
const DIA = process.env.SENTINEL_DIALECT_DIR ?? (RUN ? path.join(RUN, "..", "dialect") : "");

const json = (body: unknown, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
const err = (status: number, error: string, detail: string | string[]) => json({ error, detail }, status);
const readJson = <T,>(p: string): T | null => { try { return JSON.parse(readFileSync(p, "utf8")) as T; } catch { return null; } };
/** Python's json writes Infinity/NaN for unbounded thresholds; read them as null instead of failing the whole file. */
const readJsonLenient = <T,>(p: string): T | null => { try { return JSON.parse(readFileSync(p, "utf8").replace(/-?\bInfinity\b|\bNaN\b/g, "null")) as T; } catch { return null; } };
const safeId = (s: string) => /^[A-Za-z0-9_-]{1,80}$/.test(s);
const inside = (root: string, p: string) => path.resolve(p).startsWith(path.resolve(root) + path.sep);

type Run = { run_id: string; mode: "reference" | "asr"; created_at: string; notes: string[]; system: string | null; provider: string | null };
function run(): Run | null {
  const r = readJson<Record<string, unknown>>(path.join(RUN, "results.json"));
  if (!r) return null;
  return { run_id: String(r.run_id ?? "run"), mode: r.mode === "asr" ? "asr" : "reference", created_at: String(r.created_at ?? ""),
    notes: Array.isArray(r.notes) ? (r.notes as string[]) : [], system: (r.system as string) ?? null, provider: (r.provider as string) ?? null };
}
const suffix = () => (run()?.mode === "reference" ? "_reference" : "");
/** A self-contained run folder (traces/ and transcripts/ next to results/) wins over the shared artifacts, which other
 *  runs may rewrite at any time; the shared folders are the fallback for older run layouts. */
const docDir = (kind: "traces" | "transcripts") => (existsSync(path.join(RUN, kind)) ? path.join(RUN, kind) : path.join(ART, `${kind}${suffix()}`));
const resultIds = () => (existsSync(path.join(RUN, "results")) ? readdirSync(path.join(RUN, "results")).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort() : []);

function calls() {
  const r = run();
  const variants = new Map<string, string>();
  for (const c of readJson<{ calls?: { call_id: string; variant?: string }[] }>(path.join(ART, "manifests", "inference.json"))?.calls ?? []) if (c.variant) variants.set(c.call_id, c.variant);
  const review = readJson<{ review?: number }>(path.join(REPO, "config", "thresholds.json"))?.review ?? 0.4;
  return resultIds().flatMap((id) => {
    const res = readJson<{ decision: string; risk_score: number; confidence: number | null; findings: { criterion: string; risk: number }[]; stage_errors: unknown[] }>(path.join(RUN, "results", `${id}.json`));
    if (!res) return [];
    const an = readJson<{ duration_s?: number }>(path.join(ART, "analysis", id, "analysis.json"));
    const tr = readJson<{ decision_path?: string }>(path.join(docDir("traces"), `${id}.json`));
    const top = [...res.findings].sort((x, y) => y.risk - x.risk)[0] as { reason?: string } | undefined;
    return [{
      // a failed post-decision step (trigger, snippets) leaves the call "done"; only a decisive failure is "error"
      call_id: id, status: tr?.decision_path === "stage_error" ? "error" : "done", duration_s: an?.duration_s ?? null, variant: variants.get(id) ?? null,
      decision: res.decision, risk_score: res.risk_score, confidence: res.confidence,
      criteria: [...new Set(res.findings.filter((f) => f.risk >= review).map((f) => f.criterion))],
      n_stage_errors: res.stage_errors.length, updated_at: r?.created_at ?? null, is_mock: false,
      decision_path: tr?.decision_path ?? null, reason: top?.reason ?? null,
    }];
  });
}

// ---- audio with Range support
function fileResponse(file: string, req: Request, type: string) {
  const size = statSync(file).size;
  const range = /bytes=(\d*)-(\d*)/.exec(req.headers.get("range") ?? "");
  if (range) {
    const start = range[1] ? Number(range[1]) : Math.max(0, size - Number(range[2]));
    const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    const stream = Readable.toWeb(createReadStream(file, { start, end })) as ReadableStream;
    return new Response(stream, { status: 206, headers: { "Content-Type": type, "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${size}`, "Content-Length": String(end - start + 1) } });
  }
  const stream = Readable.toWeb(createReadStream(file)) as ReadableStream;
  return new Response(stream, { headers: { "Content-Type": type, "Accept-Ranges": "bytes", "Content-Length": String(size) } });
}

// ---- exact what-if through pipeline/simulate.py (one helper process per server)
type Pending = (line: string) => void;
let helper: { proc: ChildProcessWithoutNullStreams; queue: Pending[]; ready: Promise<void> } | null = null;
function getHelper() {
  if (helper && helper.proc.exitCode == null) return helper;
  const py = existsSync(path.join(REPO, ".venv", "bin", "python")) ? path.join(REPO, ".venv", "bin", "python") : "python3";
  const proc = spawn(py, [path.join(REPO, "web", "scripts", "run_simulate.py"), ART, RUN, run()?.mode ?? "reference"], { cwd: REPO });
  const queue: Pending[] = [];
  let markReady: () => void = () => {};
  const ready = new Promise<void>((res) => { markReady = res; });
  createInterface({ input: proc.stdout }).on("line", (line) => {
    if (line.startsWith('{"ready"')) { markReady(); return; }
    queue.shift()?.(line);
  });
  proc.stderr.on("data", () => {});                       // pipeline warnings; never logged with data
  proc.on("exit", () => { for (const p of queue.splice(0)) p(JSON.stringify({ error: { status: 500, detail: "simulator stopped" } })); helper = null; });
  helper = { proc, queue, ready };
  return helper;
}
type HelperOut = { ok?: unknown; error?: { status: number; detail: string | string[] } };
async function ask(req: Record<string, unknown>): Promise<HelperOut> {
  const h = getHelper();
  await h.ready;
  const line = await new Promise<string>((res) => { h.queue.push(res); h.proc.stdin.write(JSON.stringify(req) + "\n"); });
  return JSON.parse(line) as HelperOut;
}
const answer = (out: HelperOut) => (out.ok !== undefined ? json(out.ok) : err(out.error?.status ?? 500, out.error?.status === 422 ? "invalid" : "internal", out.error?.detail ?? "simulation failed"));
/** The simulator re-decides with the pipeline's decide step. If its baseline does not reproduce this run's own decisions
 *  (e.g. a run decided by the AI judge while the simulator re-decides with facts → rules), its numbers would be invented:
 *  refuse with a plain reason instead. */
function baselineMismatch(out: HelperOut): string | null {
  const before = (out.ok as { counts?: { before?: Record<string, number> } } | undefined)?.counts?.before;
  if (!before) return null;
  const run: Record<string, number> = { alarm: 0, review: 0, no_alert: 0 };
  for (const c of calls()) run[c.decision] = (run[c.decision] ?? 0) + 1;
  const same = ["alarm", "review", "no_alert"].every((k) => (before[k] ?? 0) === (run[k] ?? 0));
  const n = (k: number, w: string) => `${k} ${w}${k === 1 ? "" : "s"}`;
  return same ? null : `This preview cannot re-decide this run yet: its decisions come from the AI judge (${n(run.alarm, "alert")}, ${n(run.review, "review")}), while the preview re-decides with facts → rules (${n(before.alarm ?? 0, "alert")}, ${n(before.review ?? 0, "review")}). The judge threshold preview comes with the judge-threshold update.`;
}
const simulate = async (patch: unknown) => {
  const out = await ask({ patch, feedback: [...feedback.values()] });
  const why = out.ok !== undefined ? baselineMismatch(out) : null;
  return why ? err(409, "baseline_mismatch", why) : answer(out);
};

/** POST /settings/preview (docs/API.md) from the exact simulator + the pipeline's own keyword matcher. */
async function preview(body: Record<string, unknown> | null): Promise<Response> {
  const patch: Record<string, unknown> = {};
  if (body?.thresholds) patch.thresholds = body.thresholds;
  if (body?.keywords) patch.keywords = body.keywords;
  if (body?.rules) patch.rules = body.rules;
  const sim = await ask({ patch, feedback: [] });
  if (sim.ok === undefined) return answer(sim);
  const why = baselineMismatch(sim);
  const kwDoc = body?.keywords ?? readJson(path.join(REPO, "config", "keywords.json"));
  const hits = await ask({ op: "hits", keywords: kwDoc });
  if (hits.ok === undefined) return answer(hits);
  // keyword hit counts are the pipeline's own matcher and valid on any run; only the decision flips depend on the simulator
  if (why) return json({ decision_counts: null, changed: [], keyword_hit_counts: hits.ok, rule_fire_counts: {}, note: why });
  const r = sim.ok as { counts: { before: Record<string, number>; after: Record<string, number> }; flipped: { call_id: string; before: string; after: string; risk_before: number; risk_after: number }[] };
  return json({
    decision_counts: r.counts,
    changed: r.flipped.map((f) => ({ call_id: f.call_id, decision_before: f.before, decision_after: f.after, risk_before: f.risk_before, risk_after: f.risk_after })),
    keyword_hit_counts: hits.ok, rule_fire_counts: {},
  });
}

// ---- "how each method decided": the strategy comparison run (scripts/strategy_lab.py, T4). Decisions and reasons
// per strategy only; the file carries no gold labels, and nothing else of it is passed on.
function strategies(id: string): Response {
  const lab = readJson<Record<string, Record<string, { decision?: string; risk?: number; reason?: string; criteria?: string[]; error?: boolean }>>>(path.join(ART, "bench", "strategy_lab_t4", "per_call.json"));
  const row = lab?.[id];
  if (!row) return err(404, "not_available", "This call is not in the strategy comparison run.");
  const defaults = readJson<{ default?: string; top3?: { id: string; strategy: string; description: string }[] }>(path.join(REPO, "config", "strategy_defaults.json"));
  const methods = Object.entries(row).map(([sid, v]) => ({ id: sid, decision: v.decision ?? null, risk: v.risk ?? null, reason: v.reason ?? null, criteria: v.criteria ?? [], error: !!v.error }));
  return json({ call_id: id, run: "strategy_lab_t4", default: defaults?.default ?? null, top3: defaults?.top3?.map((t) => t.id) ?? [], methods });
}

// ---- evidence behind the Quality page: 3-fold CV per fix step with the flag-all baseline (artifacts/metrics/crossval.json),
// the strategy comparison on reference transcripts (artifacts/bench/strategy_lab_t4/summary.json), and the risk-score AUC
// stated in the final report's notes. Metrics only; no labels and no per-call gold leave the files.
function qualityEvidence() {
  type Fold = { esc_f1?: number; esc_r?: number };
  type Row = { label: string; folds?: Record<string, Fold>; cv_mean?: number; cv_min?: number; cv_max?: number; all62_in_sample?: { esc_f1?: number }; flag_all_baseline?: Record<string, number> };
  const cv = readJson<{ rows?: Row[] }>(path.join(ART, "metrics", "crossval.json"));
  type Strat = { strategy?: string; description?: string; n?: number; esc_f1?: number; ci95?: { esc_f1?: [number, number] } };
  const lab = readJson<{ tuning_set?: string; strategies?: Record<string, Strat> }>(path.join(ART, "bench", "strategy_lab_t4", "summary.json"));
  const fin = readJson<{ notes?: string[]; run_id?: string }>(path.join(ART, "quality", "final_report.json"));
  const aucNote = (fin?.notes ?? []).find((n) => /AUC/i.test(n)) ?? null;
  const auc = aucNote ? Number(/AUC[^0-9]*([0-9]+\.[0-9]+)/i.exec(aucNote)?.[1] ?? NaN) : NaN;
  // judge evaluation (AUC with 95% CI per scorer) and the method comparison under one CV protocol (conditions_cv)
  type Oof = { esc_p?: number | null; esc_r?: number | null; esc_f1?: number | null; bacc?: number | null; review_load?: number | null; false_alarms?: number | null };
  const je = readJsonLenient<{ scorers?: Record<string, { auc?: { auc?: number; ci95?: [number, number]; n?: number } }>; citations_valid?: number; citations_total?: number; judge_version?: string }>(path.join(ART, "metrics", "judge_eval.json"));
  const cc = readJson<{ methods?: Record<string, { oof?: Oof; cv_bacc_mean?: number; cv_bacc_range?: [number, number] }>; ship_rule_pass?: boolean }>(path.join(ART, "metrics", "conditions_cv.json"));
  const mc = readJsonLenient<{ rows?: { method: string; auc?: number; auc_ci95?: [number, number]; bacc?: number; esc_p?: number; esc_r?: number; false_alarms?: number; review_load?: number }[]; gate_pass?: boolean; version?: string }>(path.join(ART, "metrics", "multi_check_eval.json"));
  const out = {
    judge_eval: je ? { auc: Object.fromEntries(Object.entries(je.scorers ?? {}).map(([k, v]) => [k, { value: v.auc?.auc ?? null, ci: v.auc?.ci95 ?? null, n: v.auc?.n ?? null }])),
      citations_valid: je.citations_valid ?? null, citations_total: je.citations_total ?? null, judge_version: je.judge_version ?? null } : null,
    // multi-check judge vs the single judge on all 62 case calls (zero-shot: no tuned parameter), when the master wrote it
    multi_check: mc ? { gate_pass: mc.gate_pass ?? null, version: mc.version ?? null, rows: (mc.rows ?? []).map((r) => ({ method: r.method, auc: r.auc ?? null,
      auc_ci: r.auc_ci95 ?? null, bacc: r.bacc ?? null, esc_p: r.esc_p ?? null, esc_r: r.esc_r ?? null, false_alarms: r.false_alarms ?? null, review_load: r.review_load ?? null })) } : null,
    methods: cc ? { ship_rule_pass: cc.ship_rule_pass ?? null, rows: Object.entries(cc.methods ?? {}).map(([name, v]) => ({ name, oof: v.oof ?? null, cv_bacc: v.cv_bacc_mean ?? null, cv_bacc_range: v.cv_bacc_range ?? null })) } : null,
  };
  return {
    ...out,
    crossval: (cv?.rows ?? []).map((r) => ({
      label: r.label, folds: Object.fromEntries(Object.entries(r.folds ?? {}).map(([k, v]) => [k, v.esc_f1 ?? null])),
      recall_folds: Object.fromEntries(Object.entries(r.folds ?? {}).map(([k, v]) => [k, v.esc_r ?? null])),
      cv_mean: r.cv_mean ?? null, cv_min: r.cv_min ?? null, cv_max: r.cv_max ?? null, all62: r.all62_in_sample?.esc_f1 ?? null, flag_all: r.flag_all_baseline ?? null,
    })),
    strategies: lab ? { tuning_set: lab.tuning_set ?? null, rows: Object.entries(lab.strategies ?? {}).map(([sid, v]) => ({ id: sid, strategy: v.strategy ?? null, description: v.description ?? null, n: v.n ?? null, esc_f1: v.esc_f1 ?? null, ci: v.ci95?.esc_f1 ?? null })) } : null,
    auc: Number.isFinite(auc) ? { value: auc, run_id: fin?.run_id ?? null, note: aucNote } : null,
  };
}

// ---- an uploaded call: served from its own folder under the uploads dir; 202 while the pipeline is still running
function uploadGet(req: Request, id: string, b: string | undefined, name: string | undefined): Response {
  const P = uploadPaths(id);
  if (b === "events") return eventStream(id);
  const job = runningJob(id);
  if (!b) {
    if (job) return json({ call_id: id, status: "processing", duration_s: null, variant: null, decision: null, risk_score: null, confidence: null, criteria: [], n_stage_errors: 0, updated_at: null, is_mock: false }, 202);
    return existsSync(P.result) ? json(readJson(P.result)) : err(404, "not_found", `Unknown call ${id}`);
  }
  const doc = (f: string) => (existsSync(f) ? json(readJson(f)) : err(404, "not_available", `${b} not available for ${id}`));
  if (b === "transcript") return doc(P.transcript);
  if (b === "trace") return doc(P.trace);
  if (b === "analysis") return doc(P.analysis);
  if (b === "dialect") return DIA ? doc(path.join(DIA, `${id}.json`)) : err(404, "not_available", "No language estimate.");
  if (b === "audio") return existsSync(P.audio) ? fileResponse(P.audio, req, "audio/wav") : err(404, "not_available", "No audio.");
  if (b === "snippets" && name) { const f = path.join(P.snippets, name); return inside(P.snippets, f) && existsSync(f) ? fileResponse(f, req, "audio/wav") : err(404, "not_available", "No snippet."); }
  return err(404, "not_available", `${b} not available for an uploaded call`);
}

// ---- feedback in memory (this server only)
const feedback = new Map<string, Record<string, unknown>>();
const VERDICTS = ["false_alarm", "missed", "correct", "escalate"];

export async function GET(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  if (!RUN || !ART) return err(503, "not_configured", "Local-run fallback: set SENTINEL_RUN_DIR and SENTINEL_ARTIFACTS_DIR.");
  const p = (await ctx.params).path;
  const [a, id, b, name] = p;
  if (a === "run" && p.length === 1) return json({ ...run(), source: "local files (read-only fallback, not the API)" });
  if (a === "calls" && p.length === 1) return json([...calls(), ...uploadRows()]);
  if (a === "feedback") return json([...feedback.values()]);
  if (a === "audit" || a === "events") return a === "audit" ? json([]) : new Response(null, { status: 204 });
  if (a === "settings" && id === "thresholds") {
    const t = readJson<{ alarm: number; review: number; confidence_gate: number; keyword_review?: { enabled: boolean; min_segments: number } }>(path.join(REPO, "config", "thresholds.json"));
    return t ? json({ alarm: t.alarm, review: t.review, confidence_gate: t.confidence_gate, ...(t.keyword_review ? { keyword_review: t.keyword_review } : {}) }) : err(404, "not_available", "thresholds.json not found");
  }
  if (a === "settings" && id === "rules") return answer(await ask({ op: "rules" }));
  if (a === "settings" && id === "keywords") {
    const k = readJson(path.join(REPO, "config", "keywords.json"));
    return k ? json(k) : err(404, "not_available", "keywords.json not found");
  }
  if (a === "evidence" && id === "quality") return json(qualityEvidence());
  if (a === "evidence" && id === "threshold-curve") {
    const c = readJsonLenient(path.join(ART, "metrics", "threshold_curve.json"));
    return c ? json(c) : err(404, "not_available", "No threshold curve for this run yet.");
  }
  if (a === "quality") {
    const dir = path.join(ART, "quality");
    type Rep = { report_id?: string; run_id?: string; split?: string; mode?: string; system?: string; created_at?: string; is_mock?: boolean };
    const reps = (existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".json")) : [])
      .map((f) => readJson<Rep>(path.join(dir, f))).filter((x): x is Rep => !!x?.report_id && !!x.created_at)
      .sort((x, y) => String(y.created_at).localeCompare(String(x.created_at)));
    if (p.length === 1) return json(reps.map((x) => ({ report_id: x.report_id, run_id: x.run_id, split: x.split, mode: x.mode, system: x.system, created_at: x.created_at, is_mock: !!x.is_mock })));
    const hit = reps.find((x) => x.report_id === id);
    return hit ? json(hit) : err(404, "not_found", `Unknown report ${id}`);
  }
  if (a !== "calls" || !id || !safeId(id)) return err(404, "not_found", `No route /${p.join("/")} in the local-run fallback.`);
  if (isUploadId(id)) return uploadGet(req, id, b, name);
  if (!existsSync(path.join(RUN, "results", `${id}.json`))) return err(404, "not_found", `Unknown call ${id}`);
  if (!b) return json(readJson(path.join(RUN, "results", `${id}.json`)));
  const doc = (f: string) => (existsSync(f) ? json(readJson(f)) : err(404, "not_available", `${b} not available for ${id}`));
  if (b === "transcript") return doc(path.join(docDir("transcripts"), `${id}.json`));
  if (b === "trace") return doc(path.join(docDir("traces"), `${id}.json`));
  if (b === "analysis") return doc(path.join(ART, "analysis", id, "analysis.json"));
  if (b === "speakers") return SPK ? doc(path.join(SPK, `${id}.json`)) : err(404, "not_available", "No speaker roles.");
  if (b === "dialect") return DIA ? doc(path.join(DIA, `${id}.json`)) : err(404, "not_available", "No language estimate.");
  if (b === "audio") {
    const f = path.join(ART, "audio", `${id}.wav`);
    return existsSync(f) ? fileResponse(f, req, "audio/wav") : err(404, "not_available", "No audio for this call.");
  }
  if (b === "snippets" && name) {
    const dir = path.join(RUN, "snippets", id), f = path.join(dir, name);
    return inside(dir, f) && existsSync(f) ? fileResponse(f, req, "audio/wav") : err(404, "not_available", "No snippet.");
  }
  if (b === "events") return new Response(null, { status: 204 });
  if (b === "strategies") return strategies(id);
  if (b === "judge") { const f = path.join(RUN, "judge", `${id}.json`); return existsSync(f) ? json(readJson(f)) : err(404, "not_available", "No AI judge verdict for this call in this run."); }
  return err(404, "not_found", `No route /${p.join("/")}`);
}

export async function POST(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  if (!RUN || !ART) return err(503, "not_configured", "Local-run fallback: set SENTINEL_RUN_DIR and SENTINEL_ARTIFACTS_DIR.");
  const [a] = (await ctx.params).path;
  if (a === "calls" && (await ctx.params).path.length === 1) {
    const form = await req.formData().catch(() => null);
    const file = form?.get("file");
    if (!(file instanceof File)) return err(422, "invalid", "Send one .wav as multipart field 'file'.");
    const r = await startUpload(file);
    return r.ok ? json(r.row, 201) : err(r.status, r.error, r.detail);
  }
  const body = await req.json().catch(() => null) as Record<string, unknown> | null;
  if (a === "simulate") return simulate(body?.patch ?? {});
  const segs = (await ctx.params).path;
  if (a === "calls" && segs[2] === "report" && safeId(segs[1] ?? "")) return report(segs[1]);
  if (a === "settings" && (await ctx.params).path[1] === "preview") return preview(body);
  if (a === "feedback") {
    const { call_id, verdict, note } = (body ?? {}) as { call_id?: string; verdict?: string; note?: string };
    if (!call_id || !safeId(call_id) || !existsSync(path.join(RUN, "results", `${call_id}.json`))) return err(404, "not_found", `Unknown call ${call_id}`);
    if (!verdict || !VERDICTS.includes(verdict)) return err(422, "invalid", `verdict must be one of ${VERDICTS.join(", ")}`);
    const res = readJson<{ decision: string }>(path.join(RUN, "results", `${call_id}.json`));
    const entry = { call_id, verdict, ts: new Date().toISOString().replace(/\.\d+Z$/, "Z"), decision_at_feedback: res?.decision, note: note?.trim() || null, config_version: null, is_mock: false };
    feedback.set(call_id, entry);
    return json(entry, 201);
  }
  return err(409, "read_only", "This is the read-only local-run fallback: uploads and settings changes need the API.");
}

/** POST /calls/{id}/report, dry run only: the payloads pipeline/trigger.py would send, built in memory, nothing written or sent. */
function report(id: string): Response {
  const res = readJson<{ decision: string; findings: { criterion: string; risk: number; reason: string; evidence: { text: string; start_s: number | null }[] }[] }>(path.join(RUN, "results", `${id}.json`));
  if (!res) return err(404, "not_found", `Unknown call ${id}`);
  const fs = res.findings.filter((f) => f.risk > 0);
  if (!fs.length) return err(409, "conflict", "No finding to report for this call.");
  const fb = feedback.get(id);
  const label = fb && (fb.verdict === "correct" || fb.verdict === "missed") ? "confirmed fraud" : res.decision;
  const records = fs.map((f) => {
    const t = f.evidence[0]?.start_s;
    const quote = f.evidence[0]?.text ? ` Quote: "${f.evidence[0].text.slice(0, 300)}"` : "";
    return { mode: "dry-run", payload: { url: `http://127.0.0.1/calls/${id}${t != null ? `?t=${Math.floor(t)}` : ""}`, title: `${label}: ${f.criterion} in ${id}`.slice(0, 200), description: `${f.reason} (risk ${f.risk.toFixed(2)}).${quote}`.slice(0, 2000) } };
  });
  return json({ call_id: id, dry_run: true, records, errors: [] }, 201);
}

export async function PUT() {
  return err(409, "read_only", "Read-only local run: settings can be previewed here, but saving needs the API.");
}
