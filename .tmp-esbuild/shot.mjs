import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9333;
const profile = mkdtempSync(join(tmpdir(), "friday-shot-"));
const chrome = spawn(CHROME, [
  "--headless=new",
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`,
  "--no-first-run",
  "--no-default-browser-check",
  "--enable-unsafe-swiftshader",
  "--hide-scrollbars",
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function json(path, init) {
  for (let i = 0; i < 50; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}${path}`, init);
      if (res.ok) return await res.json();
    } catch {}
    await sleep(200);
  }
  throw new Error(`CDP endpoint not reachable: ${path}`);
}

const target = await json("/json/new?about:blank", { method: "PUT" });
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener("open", resolve, { once: true });
  ws.addEventListener("error", reject, { once: true });
});

let id = 0;
const pending = new Map();
const events = [];
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  } else if (msg.method) {
    events.push(msg);
  }
});

function send(method, params = {}) {
  id += 1;
  const current = id;
  ws.send(JSON.stringify({ id: current, method, params }));
  return new Promise((resolve, reject) => pending.set(current, { resolve, reject }));
}

async function waitForEvent(name, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const index = events.findIndex((e) => e.method === name);
    if (index >= 0) return events.splice(index, 1)[0];
    await sleep(100);
  }
  throw new Error(`timeout waiting for ${name}`);
}

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
});
await send("Page.navigate", { url: "http://127.0.0.1:5173" });
let loaded = false;
const loadStart = Date.now();
while (!loaded && Date.now() - loadStart < 30000) {
  loaded = events.some((e) => e.method === "Page.loadEventFired") ||
    (await send("Runtime.evaluate", {
      expression: "document.readyState",
      returnByValue: true,
    })).result.value === "complete";
  if (!loaded) await sleep(200);
}
await sleep(2500);

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text + " " + JSON.stringify(result.exceptionDetails.exception?.description ?? ""));
  }
  return result.result.value;
}

async function shot(name) {
  const result = await send("Page.captureScreenshot", { format: "png" });
  const file = join(process.cwd(), `.tmp-esbuild/${name}.png`);
  writeFileSync(file, Buffer.from(result.data, "base64"));
  return file;
}

const files = [];
for (const phase of ["listening", "thinking", "speaking"]) {
  await evaluate(`(async () => { const m = await import('/src/state/voiceActivity.ts'); m.setLocalVoicePhase('${phase}'); return true; })()`);
  await sleep(1800);
  const info = await evaluate(`(() => {
    const o = document.querySelector('.voice-hologram-overlay');
    const sphere = document.querySelector('.holographic-sphere');
    const scene = document.querySelector('.voice-hologram-scene');
    const canvas = document.querySelector('.holographic-sphere canvas');
    return {
      phase: '${phase}',
      stage: o?.getAttribute('data-stage') ?? null,
      label: document.querySelector('.voice-hologram-label')?.textContent ?? null,
      sphereRect: sphere ? sphere.getBoundingClientRect().toJSON() : null,
      canvasSize: canvas ? { w: canvas.width, h: canvas.height } : null,
      reflect: scene ? getComputedStyle(scene).webkitBoxReflect : null,
      overlayOpacity: o ? getComputedStyle(o).opacity : null,
    };
  })()`);
  files.push({ info, file: await shot(phase) });
}

await evaluate(`(async () => { const m = await import('/src/state/voiceActivity.ts'); m.setLocalVoicePhase('idle'); return true; })()`);
await sleep(1200);
const idle = await evaluate(`(() => ({ overlay: !!document.querySelector('.voice-hologram-overlay') }))()`);

console.log(JSON.stringify({ files, idle }, null, 2));
ws.close();
chrome.kill();
