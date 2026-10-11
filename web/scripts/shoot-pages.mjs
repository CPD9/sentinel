#!/usr/bin/env node
// Full-page screenshots of every screen, in dark and light, for the PR and the slides:
//   node scripts/shoot-pages.mjs [base_url=http://127.0.0.1:3101] [out=demo-shots/pages] [themes=dark,light]
// System Chrome over the DevTools protocol with Node's built-in WebSocket: no new dependency. Output is gitignored.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const BASE = process.argv[2] ?? "http://127.0.0.1:3101";
const WEB = path.resolve(import.meta.dirname, "..");
const OUT = path.resolve(WEB, process.argv[3] ?? "demo-shots/pages");
const THEMES = (process.argv[4] ?? "dark,light").split(",");
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const demo = readFileSync(path.join(WEB, "lib/demo.ts"), "utf8");
const ALERT = process.env.NEXT_PUBLIC_DEMO_ALERT || /DEMO_ALERT = [^"]*"([^"]+)"/.exec(demo)[1];
const HARMLESS = process.env.NEXT_PUBLIC_DEMO_HARMLESS || /DEMO_HARMLESS = [^"]*"([^"]+)"/.exec(demo)[1];
const PAGES = [
  ["01-overview", "/overview"], ["02-inbox", `/?call=${ALERT}`], ["03-processing", `/calls/${ALERT}/processing`],
  ["04-call-alert", `/calls/${ALERT}`], ["05-call-reasoning", `/calls/${ALERT}?tab=reasoning`], ["06-call-audio", `/calls/${ALERT}?tab=audio`],
  ["07-call-audit-record", `/calls/${ALERT}?tab=audit`], ["08-call-harmless", `/calls/${HARMLESS}`], ["09-threshold", "/settings/threshold"],
  ["10-keywords", "/settings/keywords"], ["11-quality", "/quality"], ["12-how-it-runs", "/how-it-runs"], ["13-model-card", "/model-card"],
];
const W = 1920, H = 1080, PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(path.join(tmpdir(), "sentinel-shots-"));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--headless=new", "--hide-scrollbars", `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
let ws, id = 0; const pending = new Map();
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
try {
  let t; for (let i = 0; i < 50 && !t; i++) { await sleep(200); t = await fetch(`http://127.0.0.1:${PORT}/json/list`).then((r) => r.json()).then((l) => l.find((x) => x.type === "page")).catch(() => null); }
  ws = new WebSocket(t.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const msg = JSON.parse(m.data); const p = pending.get(msg.id); if (p) { pending.delete(msg.id); msg.error ? p.rej(new Error(msg.error.message)) : p.res(msg.result); } };
  await send("Page.enable");
  for (const theme of THEMES) {
    const dir = path.join(OUT, theme); mkdirSync(dir, { recursive: true });
    for (const [name, url] of PAGES) {
      await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
      await send("Page.navigate", { url: `${BASE}${url}${url.includes("?") ? "&" : "?"}theme=${theme}` });
      await sleep(4500);
      const { result } = await send("Runtime.evaluate", { expression: "Math.min(9000, document.documentElement.scrollHeight)", returnByValue: true });
      await send("Emulation.setDeviceMetricsOverride", { width: W, height: Math.max(H, result.value), deviceScaleFactor: 1, mobile: false });
      await sleep(600);
      const shot = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(path.join(dir, `${name}.png`), Buffer.from(shot.data, "base64"));
      console.log(`${theme}/${name}.png  ${url}`);
    }
  }
} finally {
  try { ws?.close(); } catch { /* closed */ }
  chrome.kill(); await sleep(500);
  try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* temp */ }
}
