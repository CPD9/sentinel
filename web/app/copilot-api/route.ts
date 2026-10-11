// COPILOT: grounded questions about one call or the whole run, answered by the self-hosted LLM from the provider
// registry (pipeline/llm.py get_client, default builder_pod) through web/scripts/copilot.py.
//   POST {scope: "call"|"all", call_id?, question, history?}  -> NDJSON stream of validated claims (see copilot.py)
//   GET  ?patterns=1                                          -> entities and repeated phrasing across calls (no LLM)
// Loopback only. One LLM request at a time (the pod serves one builder); up to MAX_QUEUE wait, the rest get 429.
// Writes nothing: no chat history on disk, no logging of questions or answers.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RUN = process.env.SENTINEL_RUN_DIR ?? "";
const ART = process.env.SENTINEL_ARTIFACTS_DIR ?? "";
const REPO = path.resolve(process.cwd(), "..");
const MAX_QUEUE = 3;

const json = (body: unknown, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
const safeId = (s: string) => /^[A-Za-z0-9_-]{1,80}$/.test(s);
const LOOPBACK = /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/;

function local(req: Request): boolean {
  const host = req.headers.get("host") ?? "";
  const origin = req.headers.get("origin");
  if (!LOOPBACK.test(host)) return false;
  if (origin) { try { return LOOPBACK.test(new URL(origin).host); } catch { return false; } }
  return true;
}

function helper(req: Record<string, unknown>, signal?: AbortSignal) {
  const py = existsSync(path.join(REPO, ".venv", "bin", "python")) ? path.join(REPO, ".venv", "bin", "python") : "python3";
  const proc = spawn(py, [path.join(REPO, "web", "scripts", "copilot.py"), ART, RUN], { cwd: REPO });
  proc.stderr.on("data", () => {});                       // never logged: may carry call content
  proc.stdin.end(JSON.stringify(req) + "\n");
  signal?.addEventListener("abort", () => proc.kill());
  return proc;
}

// ---- one LLM request at a time
let tail: Promise<void> = Promise.resolve();
let waiting = 0;
function acquire(): { ready: Promise<void>; release: () => void } {
  let release: () => void = () => {};
  const mine = new Promise<void>((res) => { release = res; });
  const ready = tail;
  tail = tail.then(() => mine);
  return { ready, release };
}

let patternsMemo: { run: string; body: unknown } | null = null;

export async function GET(req: Request) {
  if (!local(req)) return json({ error: "forbidden", detail: "loopback only" }, 403);
  if (!RUN || !ART) return json({ error: "not_configured", detail: "Set SENTINEL_RUN_DIR and SENTINEL_ARTIFACTS_DIR." }, 503);
  if (!new URL(req.url).searchParams.has("patterns")) return json({ error: "not_found" }, 404);
  if (patternsMemo?.run === RUN) return json(patternsMemo.body);
  const proc = helper({ op: "patterns" });
  let out = "";
  for await (const chunk of proc.stdout) out += chunk;
  try {
    const body = JSON.parse(out);
    if (body.type !== "patterns") return json({ error: "internal", detail: body.detail ?? "patterns failed" }, 500);
    patternsMemo = { run: RUN, body };
    return json(body);
  } catch { return json({ error: "internal", detail: "patterns failed" }, 500); }
}

export async function POST(req: Request) {
  if (!local(req)) return json({ error: "forbidden", detail: "loopback only" }, 403);
  if (!RUN || !ART) return json({ error: "not_configured", detail: "Set SENTINEL_RUN_DIR and SENTINEL_ARTIFACTS_DIR." }, 503);
  let body: Record<string, unknown>;
  try { body = (await req.json()) as Record<string, unknown>; } catch { return json({ error: "invalid", detail: "JSON body expected" }, 422); }
  const scope = body.scope === "all" ? "all" : "call";
  const question = typeof body.question === "string" ? body.question.trim() : "";
  const callId = typeof body.call_id === "string" ? body.call_id : "";
  if (!question || question.length > 1000) return json({ error: "invalid", detail: "question: 1–1000 characters" }, 422);
  if (scope === "call" && !safeId(callId)) return json({ error: "invalid", detail: "call_id" }, 422);
  if (waiting >= MAX_QUEUE) return json({ error: "busy", detail: "The copilot is answering other questions; try again shortly." }, 429);
  const history = Array.isArray(body.history) ? body.history.slice(-2) : [];

  const enc = new TextEncoder();
  const ac = new AbortController();
  req.signal.addEventListener("abort", () => ac.abort());
  const lock = acquire();
  waiting++;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (ev: unknown) => { try { controller.enqueue(enc.encode(JSON.stringify(ev) + "\n")); } catch { /* client gone */ } };
      let queued = true;
      const t = setTimeout(() => { if (queued) send({ type: "queued" }); }, 150);
      try {
        await lock.ready;
        queued = false;
        clearTimeout(t);
        waiting--;
        if (ac.signal.aborted) return;
        const proc = helper({ op: "ask", scope, call_id: callId, question, history }, ac.signal);
        for await (const line of createInterface({ input: proc.stdout })) if (line.trim()) controller.enqueue(enc.encode(line + "\n"));
        await new Promise<void>((res) => (proc.exitCode != null ? res() : proc.on("exit", () => res())));
        if (proc.exitCode && !ac.signal.aborted) send({ type: "error", detail: "copilot helper failed" });
      } catch {
        send({ type: "error", detail: "copilot failed" });
      } finally {
        if (queued) { clearTimeout(t); waiting--; }
        lock.release();
        try { controller.close(); } catch { /* already closed */ }
      }
    },
    cancel() { ac.abort(); },
  });
  return new Response(stream, { headers: { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-store", "X-Accel-Buffering": "no" } });
}
