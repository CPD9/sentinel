// Model arena data (scripts/arena.py output), read-only, in every data mode.
//   GET ?f=leaderboard | pool      → artifacts/arena/leaderboard.json | duel_pool.json
//   GET ?transcript=<call_id>      → artifacts/transcripts/<id>.json, ONLY for ids in the case manifest
// No POST: nothing is uploaded or written here. Votes live in the officer's browser (lib/data-arena.ts).
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// turbopackIgnore: artifacts/ is runtime data, not something to trace into the build output.
const ART = process.env.SENTINEL_ARTIFACTS_DIR || path.resolve(/* turbopackIgnore: true */ process.cwd(), "..", "artifacts");
const FILES: Record<string, string> = { leaderboard: "arena/leaderboard.json", pool: "arena/duel_pool.json" };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
const err = (status: number, error: string, detail: string) => json({ error, detail }, status);

function manifestIds(): Set<string> {
  const p = path.join(ART, "manifests", "inference.json");
  if (!existsSync(p)) return new Set();
  const m = JSON.parse(readFileSync(p, "utf-8")) as { calls: { call_id: string }[] };
  return new Set(m.calls.map((c) => c.call_id));
}

export async function GET(req: Request) {
  const q = new URL(req.url).searchParams;
  const t = q.get("transcript");
  if (t !== null) {
    if (!manifestIds().has(t)) return err(404, "not_found", "not a case-manifest call");
    const p = path.join(ART, "transcripts", `${t}.json`);
    return existsSync(p) ? json(JSON.parse(readFileSync(p, "utf-8"))) : err(404, "not_found", "no transcript");
  }
  const rel = FILES[q.get("f") ?? ""];
  if (!rel) return err(400, "bad_request", "f must be leaderboard or pool");
  const p = path.join(ART, rel);
  if (!existsSync(p)) return err(404, "not_found", `${rel} missing: run scripts/arena.py`);
  return json(JSON.parse(readFileSync(p, "utf-8")));
}
