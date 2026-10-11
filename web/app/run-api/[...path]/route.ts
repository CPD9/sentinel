// LOCAL-RUN FALLBACK, read-only. Serves one finished pipeline run in the shapes of docs/API.md, for as long as the
// FastAPI service has no real mode. Enabled only when the web app runs with NEXT_PUBLIC_API_PREFIX=/run-api and
// SENTINEL_RUN_DIR (the run's out/ folder) + SENTINEL_ARTIFACTS_DIR (its artifacts/ folder) are set. Swapping in a
// new run = pointing the two variables at it.
//   reads    results/*.json (+ results.json), transcripts[_reference]/, traces[_reference]/, analysis/<id>/analysis.json,
//            audio/<id>.wav (Range requests), out/snippets/<id>/, artifacts/manifests/inference.json (variant only:
//            neutral ids, never evaluation.json), artifacts/quality/final_report.json, config/*.json of the repo
//   what-if  POST /simulate runs pipeline/simulate.py (exact decide.py over the cached facts) in a helper process
//   writes   nothing on disk. Feedback lives in this server's memory until restart; saving settings is refused (409).
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createReadStream, existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { createInterface } from "node:readline";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RUN = process.env.SENTINEL_RUN_DIR ?? "";
const ART = process.env.SENTINEL_ARTIFACTS_DIR ?? "";
const REPO = path.resolve(process.cwd(), "..");

const json = (body: unknown, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
const err = (status: number, error: string, detail: string | string[]) => json({ error, detail }, status);
const readJson = <T,>(p: string): T | null => { try { return JSON.parse(readFileSync(p, "utf8")) as T; } catch { return null; } };
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
    return [{
      call_id: id, status: res.stage_errors.length ? "error" : "done", duration_s: an?.duration_s ?? null, variant: variants.get(id) ?? null,
      decision: res.decision, risk_score: res.risk_score, confidence: res.confidence,
      criteria: [...new Set(res.findings.filter((f) => f.risk >= review).map((f) => f.criterion))],
      n_stage_errors: res.stage_errors.length, updated_at: r?.created_at ?? null, is_mock: false,
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
const simulate = async (patch: unknown) => answer(await ask({ patch, feedback: [...feedback.values()] }));

/** POST /settings/preview (docs/API.md) from the exact simulator + the pipeline's own keyword matcher. */
async function preview(body: Record<string, unknown> | null): Promise<Response> {
  const patch: Record<string, unknown> = {};
  if (body?.thresholds) patch.thresholds = body.thresholds;
  if (body?.keywords) patch.keywords = body.keywords;
  if (body?.rules) patch.rules = body.rules;
  const sim = await ask({ patch, feedback: [] });
  if (sim.ok === undefined) return answer(sim);
  const kwDoc = body?.keywords ?? readJson(path.join(REPO, "config", "keywords.json"));
  const hits = await ask({ op: "hits", keywords: kwDoc });
  if (hits.ok === undefined) return answer(hits);
  const r = sim.ok as { counts: { before: Record<string, number>; after: Record<string, number> }; flipped: { call_id: string; before: string; after: string; risk_before: number; risk_after: number }[] };
  return json({
    decision_counts: r.counts,
    changed: r.flipped.map((f) => ({ call_id: f.call_id, decision_before: f.before, decision_after: f.after, risk_before: f.risk_before, risk_after: f.risk_after })),
    keyword_hit_counts: hits.ok, rule_fire_counts: {},
  });
}

// ---- feedback in memory (this server only)
const feedback = new Map<string, Record<string, unknown>>();
const VERDICTS = ["false_alarm", "missed", "correct", "escalate"];

export async function GET(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  if (!RUN || !ART) return err(503, "not_configured", "Local-run fallback: set SENTINEL_RUN_DIR and SENTINEL_ARTIFACTS_DIR.");
  const p = (await ctx.params).path;
  const [a, id, b, name] = p;
  if (a === "run" && p.length === 1) return json({ ...run(), source: "local files (read-only fallback, not the API)" });
  if (a === "calls" && p.length === 1) return json(calls());
  if (a === "capabilities") return json({ verdicts: VERDICTS, report: false });
  if (a === "feedback") return json([...feedback.values()]);
  if (a === "audit" || a === "events") return a === "audit" ? json([]) : new Response(null, { status: 204 });
  if (a === "settings" && id === "thresholds") {
    const t = readJson<Record<string, number>>(path.join(REPO, "config", "thresholds.json"));
    return t ? json({ alarm: t.alarm, review: t.review, confidence_gate: t.confidence_gate }) : err(404, "not_available", "thresholds.json not found");
  }
  if (a === "settings" && id === "rules") return answer(await ask({ op: "rules" }));
  if (a === "settings" && id === "keywords") {
    const k = readJson(path.join(REPO, "config", "keywords.json"));
    return k ? json(k) : err(404, "not_available", "keywords.json not found");
  }
  if (a === "quality") {
    const rep = readJson<{ report_id?: string; run_id?: string; split?: string; mode?: string; system?: string; created_at?: string }>(path.join(ART, "quality", "final_report.json"));
    if (!rep?.report_id) return p.length === 1 ? json([]) : err(404, "not_found", "No quality report in this run yet.");
    if (p.length === 1) return json([{ report_id: rep.report_id, run_id: rep.run_id, split: rep.split, mode: rep.mode, system: rep.system, created_at: rep.created_at, is_mock: false }]);
    return id === rep.report_id ? json(rep) : err(404, "not_found", `Unknown report ${id}`);
  }
  if (a !== "calls" || !id || !safeId(id)) return err(404, "not_found", `No route /${p.join("/")} in the local-run fallback.`);
  if (!existsSync(path.join(RUN, "results", `${id}.json`))) return err(404, "not_found", `Unknown call ${id}`);
  if (!b) return json(readJson(path.join(RUN, "results", `${id}.json`)));
  const doc = (f: string) => (existsSync(f) ? json(readJson(f)) : err(404, "not_available", `${b} not available for ${id}`));
  if (b === "transcript") return doc(path.join(ART, `transcripts${suffix()}`, `${id}.json`));
  if (b === "trace") return doc(path.join(ART, `traces${suffix()}`, `${id}.json`));
  if (b === "analysis") return doc(path.join(ART, "analysis", id, "analysis.json"));
  if (b === "audio") {
    const f = path.join(ART, "audio", `${id}.wav`);
    return existsSync(f) ? fileResponse(f, req, "audio/wav") : err(404, "not_available", "No audio for this call.");
  }
  if (b === "snippets" && name) {
    const dir = path.join(RUN, "snippets", id), f = path.join(dir, name);
    return inside(dir, f) && existsSync(f) ? fileResponse(f, req, "audio/wav") : err(404, "not_available", "No snippet.");
  }
  if (b === "events") return new Response(null, { status: 204 });
  return err(404, "not_found", `No route /${p.join("/")}`);
}

export async function POST(req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  if (!RUN || !ART) return err(503, "not_configured", "Local-run fallback: set SENTINEL_RUN_DIR and SENTINEL_ARTIFACTS_DIR.");
  const [a] = (await ctx.params).path;
  const body = await req.json().catch(() => null) as Record<string, unknown> | null;
  if (a === "simulate") return simulate(body?.patch ?? {});
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

export async function PUT() {
  return err(409, "read_only", "Read-only local run: settings can be previewed here, but saving needs the API.");
}
