#!/usr/bin/env node
// Backup demo recording: walks the 8 demo steps (lib/demo.ts) at presenter pace in the system Chrome and saves
//   web/demo-recording.webm          the whole walk as video (VP9, 1920×1080)
//   web/demo-shots/<nn>-<step>.png   one 1920×1080 screenshot per step
// No new dependency: Chrome is driven over the DevTools protocol with Node's built-in WebSocket, and ffmpeg (already
// required by the pipeline) assembles the frames. Both outputs are gitignored.
//   node scripts/record-demo.mjs [base_url=http://127.0.0.1:3101] [seconds_per_step=9] [theme=dark|light]
// The app must already be running on base_url (e.g. the local-run fallback on the final run).
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const BASE = process.argv[2] ?? "http://127.0.0.1:3101";
const DWELL = Number(process.argv[3] ?? 9) * 1000;
const THEME = process.argv[4] === "light" ? "light" : "dark";
const WEB = path.resolve(import.meta.dirname, "..");
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const W = 1920, H = 1080, PORT = 9333;

// the step list, read from lib/demo.ts so the recording always follows the app (hrefs are resolved by the app itself)
const n = (readFileSync(path.join(WEB, "lib/demo.ts"), "utf8").match(/\{ href: [`"]/g) ?? []).length;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(path.join(tmpdir(), "sentinel-rec-"));
const frames = mkdtempSync(path.join(tmpdir(), "sentinel-frames-"));
const shots = path.join(WEB, THEME === "light" ? "demo-shots/light" : "demo-shots");
mkdirSync(shots, { recursive: true });
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--headless=new", "--hide-scrollbars",
  `--window-size=${W},${H}`, "--force-device-scale-factor=1", "about:blank"], { stdio: "ignore" });

let ws, id = 0;
const pending = new Map(), handlers = [];
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });

try {
  let target;
  for (let i = 0; i < 50 && !target; i++) {
    await sleep(200);
    target = await fetch(`http://127.0.0.1:${PORT}/json/list`).then((r) => r.json()).then((l) => l.find((t) => t.type === "page")).catch(() => null);
  }
  if (!target) throw new Error("Chrome did not start");
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.rej(new Error(msg.error.message)) : p.res(msg.result); }
    else handlers.forEach((h) => h(msg));
  };
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });

  // video: every screencast frame is stored with its timestamp; ffmpeg gets real durations, so pacing is preserved
  const list = [];
  handlers.push((msg) => {
    if (msg.method !== "Page.screencastFrame") return;
    const f = path.join(frames, `${String(list.length).padStart(6, "0")}.jpg`);
    writeFileSync(f, Buffer.from(msg.params.data, "base64"));
    list.push({ f, t: msg.params.metadata.timestamp });
    void send("Page.screencastFrameAck", { sessionId: msg.params.sessionId });
  });

  await send("Page.navigate", { url: `${BASE}/overview?theme=${THEME}` });     // the theme is remembered for the whole walk
  await sleep(1500);
  await send("Page.navigate", { url: `${BASE}/demo` });
  await sleep(2500);
  await send("Page.startScreencast", { format: "jpeg", quality: 85, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  for (let i = 0; i < n; i++) {
    await sleep(DWELL);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    const where = await send("Runtime.evaluate", { expression: "location.pathname", returnByValue: true });
    const name = `${String(i + 1).padStart(2, "0")}-${String(where.result.value).replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "home"}.png`;
    writeFileSync(path.join(shots, name), Buffer.from(shot.data, "base64"));
    console.log(`step ${i + 1}/${n}  ${where.result.value}  → demo-shots/${name}`);
    if (i < n - 1) await send("Runtime.evaluate", { expression: "window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))" });
  }
  await send("Page.stopScreencast");

  // concat list with per-frame durations, then encode
  const concat = list.map((fr, i) => `file '${fr.f}'\nduration ${Math.max(0.02, ((list[i + 1]?.t ?? fr.t + 0.5) - fr.t)).toFixed(3)}`).join("\n") + `\nfile '${list.at(-1).f}'\n`;
  writeFileSync(path.join(frames, "list.txt"), concat);
  const out = path.join(WEB, THEME === "light" ? "demo-recording-light.webm" : "demo-recording.webm");
  const r = spawnSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", path.join(frames, "list.txt"), "-vf", `scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,fps=25`,
    "-c:v", "libvpx-vp9", "-b:v", "2M", "-deadline", "realtime", "-cpu-used", "8", out], { stdio: "inherit" });
  if (r.status !== 0) throw new Error("ffmpeg failed");
  console.log(`saved ${out} (${list.length} frames)`);
} finally {
  try { ws?.close(); } catch { /* closed */ }
  chrome.kill();
  await new Promise((r) => { if (chrome.exitCode != null) r(); else { chrome.once("exit", r); setTimeout(r, 3000); } });
  for (const d of [profile, frames]) { try { rmSync(d, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* temp dir, the OS cleans it */ } }
}
