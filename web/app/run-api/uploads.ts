// Live upload for the local-run fallback (POST /run-api/calls): one .wav at a time, processed by the real pipeline
// (web/scripts/process_upload.py → pipeline.process_call) with its events streamed to the page over SSE.
//   - checked: ≤ 50 MB, a WAV content type AND a RIFF/WAVE header
//   - stored in ~/Developer/sentinel-runs/uploads/upload_<HHMMSS>/ (own artifacts/ and out/): a fresh id, never a
//     known call id, so the shared artifacts and the recorded runs are never overwritten
//   - spawned with an argument array, no shell; the only arguments are paths and the generated id
//   - one job at a time (409 while busy); a job that runs longer than JOB_TIMEOUT_MS is stopped and ends as review
import { spawn, type ChildProcess } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";

export const UPLOADS = process.env.SENTINEL_UPLOADS_DIR ?? path.join(homedir(), "Developer", "sentinel-runs", "uploads");
const REPO = path.resolve(process.cwd(), "..");
const MAX_BYTES = 50 * 1024 * 1024;
const WAV_TYPES = new Set(["audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"]);
const JOB_TIMEOUT_MS = 8 * 60 * 1000;
const ASR_MODEL = "mobiuslabsgmbh/faster-whisper-large-v3-turbo";
export const isUploadId = (id: string) => /^upload_\d{6}(_\d+)?$/.test(id);

export interface Ev { seq: number; event: string; call_id: string; ts: string; stage: string | null; elapsed_s: number | null; cached: boolean | null; message: string | null; decision: string | null }
interface Job { id: string; dir: string; events: Ev[]; listeners: Set<(e: Ev) => void>; done: boolean; proc: ChildProcess | null; started: string }

// kept on globalThis so a dev-mode module reload does not lose a running job
const G = globalThis as unknown as { __sentinelUploads?: { jobs: Map<string, Job>; busy: string | null } };
const S = (G.__sentinelUploads ??= { jobs: new Map(), busy: null });

export const uploadDir = (id: string) => path.join(UPLOADS, id);
export const uploadPaths = (id: string) => {
  const d = uploadDir(id);
  return {
    result: path.join(d, "out", "results", `${id}.json`), trace: path.join(d, "artifacts", "traces", `${id}.json`),
    transcript: path.join(d, "artifacts", "transcripts", `${id}.json`), analysis: path.join(d, "artifacts", "analysis", id, "analysis.json"),
    audio: path.join(d, "audio.wav"), snippets: path.join(d, "out", "snippets", id), events: path.join(d, "events.jsonl"),
  };
};
export const runningJob = (id: string) => { const j = S.jobs.get(id); return j && !j.done ? j : null; };

function push(job: Job, raw: Partial<Ev> & { event: string }) {
  const e: Ev = { seq: job.events.length + 1, call_id: job.id, ts: new Date().toISOString().replace(/\.\d+Z$/, "Z"), stage: null, elapsed_s: null, cached: null, message: null, decision: null, ...raw } as Ev;
  job.events.push(e);
  try { appendFileSync(uploadPaths(job.id).events, JSON.stringify(e) + "\n"); } catch { /* the stream still works from memory */ }
  for (const l of job.listeners) l(e);
  if (e.event === "job_finished") { job.done = true; S.busy = null; }
}

/** Validates and stores the file, starts the pipeline. Returns the list row or an error. */
export async function startUpload(file: File): Promise<{ ok: true; row: Record<string, unknown> } | { ok: false; status: number; error: string; detail: string }> {
  if (S.busy && runningJob(S.busy)) return { ok: false, status: 409, error: "conflict", detail: `Another call (${S.busy}) is being processed. One upload at a time.` };
  if (file.size === 0 || file.size > MAX_BYTES) return { ok: false, status: 422, error: "invalid", detail: `The file must be between 1 byte and 50 MB (got ${(file.size / 1e6).toFixed(1)} MB).` };
  if (!WAV_TYPES.has((file.type || "").toLowerCase())) return { ok: false, status: 415, error: "unsupported", detail: `Only .wav files are accepted (got content type "${file.type || "none"}").` };
  const buf = Buffer.from(await file.arrayBuffer());
  if (buf.subarray(0, 4).toString("ascii") !== "RIFF" || buf.subarray(8, 12).toString("ascii") !== "WAVE")
    return { ok: false, status: 415, error: "unsupported", detail: "This is not a WAV file (no RIFF/WAVE header)." };

  const now = new Date();
  const hhmmss = [now.getHours(), now.getMinutes(), now.getSeconds()].map((x) => String(x).padStart(2, "0")).join("");
  let id = `upload_${hhmmss}`;
  for (let i = 2; existsSync(uploadDir(id)); i++) id = `upload_${hhmmss}_${i}`;
  const dir = uploadDir(id);
  mkdirSync(dir, { recursive: true });
  writeFileSync(uploadPaths(id).audio, buf);
  writeFileSync(path.join(dir, "upload.json"), JSON.stringify({ call_id: id, size_bytes: buf.length, created_at: now.toISOString() }));   // the original file name is not kept

  const job: Job = { id, dir, events: [], listeners: new Set(), done: false, proc: null, started: now.toISOString() };
  S.jobs.set(id, job);
  S.busy = id;
  push(job, { event: "job_queued", message: "uploaded" });

  const py = existsSync(path.join(REPO, ".venv", "bin", "python")) ? path.join(REPO, ".venv", "bin", "python") : "python3";
  const proc = spawn(py, [path.join(REPO, "web", "scripts", "process_upload.py"), uploadPaths(id).audio, id, dir],
    { cwd: REPO, env: { ...process.env, ASR_MODEL_PATH: ASR_MODEL, PYTHONUNBUFFERED: "1" }, stdio: ["ignore", "pipe", "pipe"] });
  job.proc = proc;
  let stderrTail = "";
  proc.stderr?.on("data", (d: Buffer) => { stderrTail = (stderrTail + d.toString()).slice(-600); });
  createInterface({ input: proc.stdout! }).on("line", (line) => {
    let o: Record<string, unknown>;
    try { o = JSON.parse(line); } catch { return; }                 // library output that is not an event
    if (o.event === "result") return;                               // job_finished already carries the decision
    if (o.event === "notice") { push(job, { event: "notice", stage: (o.stage as string) ?? null, message: String(o.message ?? "") }); return; }
    push(job, { event: String(o.event), stage: (o.stage as string) ?? null, elapsed_s: (o.elapsed_s as number) ?? null, cached: (o.cached as boolean) ?? null,
      message: (o.message as string) ?? null, decision: (o.decision as string) ?? null });
  });
  const timer = setTimeout(() => { if (!job.done) { proc.kill("SIGTERM"); push(job, { event: "stage_failed", stage: "pipeline", message: "Stopped after 8 minutes without finishing." }); push(job, { event: "job_finished", decision: "review" }); } }, JOB_TIMEOUT_MS);
  proc.on("exit", (code) => {
    clearTimeout(timer);
    if (!job.done) {
      push(job, { event: "stage_failed", stage: "pipeline", message: `The pipeline process stopped (exit ${code}) before finishing. ${stderrTail.split("\n").filter(Boolean).at(-1) ?? ""}`.trim() });
      push(job, { event: "job_finished", decision: "review" });
    }
  });
  proc.on("error", (e) => { if (!job.done) { push(job, { event: "stage_failed", stage: "pipeline", message: `Could not start the pipeline: ${e.message}` }); push(job, { event: "job_finished", decision: "review" }); } });

  return { ok: true, row: { call_id: id, status: "processing", duration_s: null, variant: null, decision: null, risk_score: null, confidence: null, criteria: [], n_stage_errors: 0, updated_at: job.started, is_mock: false } };
}

/** SSE: past events first, then live ones; closes after job_finished. A finished upload replays its events file. */
export function eventStream(id: string): Response {
  const job = S.jobs.get(id);
  const stored = (): Ev[] => { try { return readFileSync(uploadPaths(id).events, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)); } catch { return []; } };
  const enc = new TextEncoder();
  const frame = (e: Ev) => enc.encode(`id: ${e.seq}\nevent: ${e.event}\ndata: ${JSON.stringify(e)}\n\n`);
  let listener: ((e: Ev) => void) | null = null;
  const stream = new ReadableStream({
    start(ctrl) {
      const past = job ? [...job.events] : stored();
      for (const e of past) ctrl.enqueue(frame(e));
      if (!job || job.done) { ctrl.close(); return; }
      const ping = setInterval(() => { try { ctrl.enqueue(enc.encode(": ping\n\n")); } catch { clearInterval(ping); } }, 15000);
      listener = (e) => { try { ctrl.enqueue(frame(e)); if (e.event === "job_finished") { clearInterval(ping); job.listeners.delete(listener!); ctrl.close(); } } catch { clearInterval(ping); } };
      job.listeners.add(listener);
    },
    cancel() { if (job && listener) job.listeners.delete(listener); },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-store", Connection: "keep-alive" } });
}

/** List rows for uploads: running ones as "processing", finished ones from their result file. */
export function uploadRows(): Record<string, unknown>[] {
  if (!existsSync(UPLOADS)) return [];
  return readdirSync(UPLOADS).filter(isUploadId).sort().flatMap((id): Record<string, unknown>[] => {
    const job = runningJob(id);
    if (job) return [{ call_id: id, status: "processing", duration_s: null, variant: null, decision: null, risk_score: null, confidence: null, criteria: [], n_stage_errors: 0, updated_at: job.started, is_mock: false }];
    const p = uploadPaths(id);
    let res: { decision: string; risk_score: number; confidence: number | null; findings: { criterion: string; risk: number; reason?: string }[]; stage_errors: unknown[] } | null = null;
    try { res = JSON.parse(readFileSync(p.result, "utf8")); } catch { return []; }
    let tr: { decision_path?: string } | null = null, an: { duration_s?: number } | null = null, meta: { created_at?: string } | null = null;
    try { tr = JSON.parse(readFileSync(p.trace, "utf8")); } catch { /* none */ }
    try { an = JSON.parse(readFileSync(p.analysis, "utf8")); } catch { /* none */ }
    try { meta = JSON.parse(readFileSync(path.join(uploadDir(id), "upload.json"), "utf8")); } catch { /* none */ }
    const top = [...res!.findings].sort((x, y) => y.risk - x.risk)[0];
    return [{ call_id: id, status: tr?.decision_path === "stage_error" ? "error" : "done", duration_s: an?.duration_s ?? null, variant: null, decision: res!.decision,
      risk_score: res!.risk_score, confidence: res!.confidence, criteria: [...new Set(res!.findings.filter((f) => f.risk > 0).map((f) => f.criterion))],
      n_stage_errors: res!.stage_errors.length, updated_at: meta?.created_at ?? null, is_mock: false, decision_path: tr?.decision_path ?? null, reason: top?.reason ?? null }];
  });
}
