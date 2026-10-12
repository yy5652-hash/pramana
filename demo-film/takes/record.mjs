// Records real takes of the running Pramana app for the film.
//
//   node record.mjs <scene> [<scene> ...]        scenes are defined in scenes.mjs
//
// The app is driven in headless Google Chrome over the DevTools protocol: a visible cursor is
// moved with real mouse events, text is typed key by key, and the browser's own screencast is
// saved frame by frame with timestamps. Nothing on screen is mocked; the server is the real
// one, answering from the real knowledge base. Each take becomes
//   ../film/public/takes/<scene>.mp4   constant 30 fps, 1920x1080
//   ../film/public/takes/<scene>.json  the moments the scene marked (seconds from the start)
//
// Method adapted from this author's earlier relay-home-film/record.mjs.
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { scenes } from "./scenes.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const FILM = join(HERE, "../film");
const CHROME = process.env.CHROME || `${process.env.HOME}/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`;
const APP = process.env.PRAMANA_URL || "http://127.0.0.1:8765";
const FFMPEG = process.env.FFMPEG || "ffmpeg";
const DEBUG_PORT = 9347;
// A 1536x864 layout captured at 2x (3072x1728): at full view the UI fills the film's 1080p frame
// with type large enough to read small, and a push-in of up to 1.6x is still pixel-for-pixel sharp.
const VIEW = { width: 1536, height: 864, scale: Number(process.env.FILM_SCALE || 2) };
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const CURSOR = `
(() => {
  if (document.getElementById("film-cursor")) return;
  const c = document.createElement("div");
  c.id = "film-cursor";
  c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M5 3l14 8.5-6.2 1.4L9.6 19z" fill="#1d1c1a" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, { position: "fixed", left: "760px", top: "560px", zIndex: 2147483647, pointerEvents: "none",
    transition: "left var(--d,600ms) cubic-bezier(.3,.1,.2,1), top var(--d,600ms) cubic-bezier(.3,.1,.2,1), transform 120ms", filter: "drop-shadow(0 2px 3px rgba(0,0,0,.35))" });
  document.documentElement.append(c);
})();`;

async function connect() {
  for (let i = 0; i < 80; i += 1) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`)).json();
      const page = targets.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await wait(250);
  }
  throw new Error("Chrome did not start");
}

async function record(name) {
  const scene = scenes[name];
  if (!scene) throw new Error(`unknown scene '${name}'. Known: ${Object.keys(scenes).join(", ")}`);
  const framesDir = join(HERE, "work", name);
  rmSync(framesDir, { recursive: true, force: true });
  mkdirSync(framesDir, { recursive: true });
  mkdirSync(join(FILM, "public/takes"), { recursive: true });

  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "pramana-film-"))}`,
    `--window-size=${VIEW.width},${VIEW.height}`, `--force-device-scale-factor=${VIEW.scale}`, "--hide-scrollbars", "--force-color-profile=srgb", "--autoplay-policy=no-user-gesture-required", "--mute-audio", "about:blank"], { stdio: "ignore" });
  try {
    const socket = new WebSocket(await connect());
    await new Promise((resolve) => { socket.onopen = resolve; });
    let id = 0;
    const pending = new Map();
    const frames = [];
    const marks = [];
    let recording = false;
    let t0 = 0;
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const { resolve, reject, method } = pending.get(message.id);
        pending.delete(message.id);
        message.error ? reject(new Error(`${method}: ${message.error.message}`)) : resolve(message.result);
      } else if (message.method === "Page.screencastFrame") {
        const { data, metadata, sessionId } = message.params;
        if (recording) {
          const file = `f${String(frames.length).padStart(6, "0")}.jpg`;
          writeFileSync(join(framesDir, file), Buffer.from(data, "base64"));
          frames.push({ t: metadata.timestamp, file });
        }
        socket.send(JSON.stringify({ id: ++id, method: "Page.screencastFrameAck", params: { sessionId } }));
      } else if (message.method === "Runtime.exceptionThrown") {
        console.log("[page exception]", message.params.exceptionDetails.exception?.description?.slice(0, 300));
      }
    };
    const cdp = (method, params = {}) => new Promise((resolve, reject) => { pending.set(++id, { resolve, reject, method }); socket.send(JSON.stringify({ id, method, params })); });
    const run = async (expression) => {
      const { result, exceptionDetails } = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
      return result.value;
    };

    await cdp("Page.enable");
    await cdp("Runtime.enable");
    // The scale factor is the browser's own (--force-device-scale-factor), so the screencast is
    // delivered in device pixels: a 1536x864 layout captured at 1920x1080.
    await cdp("Emulation.setDeviceMetricsOverride", { width: VIEW.width, height: VIEW.height, deviceScaleFactor: 0, mobile: false });

    const now = () => (recording ? Date.now() / 1000 - t0 : 0);
    const mouse = { x: 760, y: 560 };
    const take = {
      api: async (path, body) => (await fetch(`${APP}/api${path}`, body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })).json(),
      run,
      wait,
      mark: (label, extra = {}) => { marks.push({ t: Number(now().toFixed(3)), label, ...extra }); console.log(`  [${now().toFixed(1)}s] ${label}`, Object.keys(extra).length ? JSON.stringify(extra).slice(0, 140) : ""); },
      // A mark that also remembers where an element is on screen (in take pixels), so the film
      // can aim its camera at it without anyone measuring a frame by hand.
      markRect: async (label, target, extra = {}) => {
        const rect = await run(`(() => { const el = ${target}; if (!el) return null; const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map((v) => Math.round(v * ${VIEW.scale})); })()`);
        if (rect) marks.push({ t: Number(now().toFixed(3)), label, rect, ...extra });
        console.log(`  [${now().toFixed(1)}s] ${label} ${rect ? rect.join(",") : "(not on screen)"}`);
      },
      goto: async (hash, prepare = "") => {
        await cdp("Page.navigate", { url: `${APP}/` });
        await wait(300);
        if (prepare) await run(prepare);
        await cdp("Page.navigate", { url: `${APP}/${hash}` });
        await run("location.reload()").catch(() => {});
        await wait(900);
        await run(CURSOR);
      },
      until: async (condition, label, timeout = 60000) => {
        const end = Date.now() + timeout;
        while (Date.now() < end) { if (await run(`Boolean(${condition})`)) return; await wait(120); }
        throw new Error(`timed out waiting for ${label}`);
      },
      // Move the visible cursor (and the real pointer) to the centre of an element or to a point.
      moveTo: async (target, ms) => {
        const point = typeof target === "string" ? await run(`(() => { const r = (${target}).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`) : target;
        const distance = Math.hypot(point.x - mouse.x, point.y - mouse.y);
        const duration = ms ?? Math.max(380, Math.min(950, distance * 1.25));
        await run(`(() => { const c = document.getElementById("film-cursor"); c.style.setProperty("--d", "${duration}ms"); c.style.left = "${point.x - 5}px"; c.style.top = "${point.y - 3}px"; })()`);
        const steps = 12;
        for (let i = 1; i <= steps; i += 1) {
          await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: mouse.x + ((point.x - mouse.x) * i) / steps, y: mouse.y + ((point.y - mouse.y) * i) / steps });
          await wait(duration / steps);
        }
        mouse.x = point.x; mouse.y = point.y;
        await wait(140);
      },
      click: async (target, ms) => {
        await take.moveTo(target, ms);
        await run(`document.getElementById("film-cursor").style.transform = "scale(.86)"`);
        await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x: mouse.x, y: mouse.y, button: "left", clickCount: 1 });
        await wait(70);
        await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x: mouse.x, y: mouse.y, button: "left", clickCount: 1 });
        await run(`document.getElementById("film-cursor").style.transform = ""`);
        await wait(160);
      },
      // Type like a person: uneven key intervals, a beat after punctuation.
      type: async (text, base = 62) => {
        for (const char of text) {
          await cdp("Input.insertText", { text: char });
          await wait(base * (0.55 + Math.random() * 0.9) + (/[,.?]/.test(char) ? 170 : char === " " ? 25 : 0));
        }
      },
      key: async (key) => {
        const code = { Enter: 13 }[key];
        await cdp("Input.dispatchKeyEvent", { type: "keyDown", key, code: key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code });
        await cdp("Input.dispatchKeyEvent", { type: "keyUp", key, code: key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code });
      },
      scroll: async (selector, top, ms = 900) => {
        await run(`(() => { const el = ${selector}; el.scrollTo({ top: ${top}, behavior: "smooth" }); })()`);
        await wait(ms);
      },
      start: async () => {
        await cdp("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: VIEW.width * VIEW.scale, maxHeight: VIEW.height * VIEW.scale, everyNthFrame: 1 });
        await wait(250);
        t0 = Date.now() / 1000;
        recording = true;
        // Chrome only sends a frame when pixels change; a small repaint guarantees a first frame.
        await run(`document.getElementById("film-cursor").style.opacity = "0.999"`);
      },
      // Keep a file the app serves (a lesson film, say) among the film's own assets.
      save: async (path, file) => {
        const response = await fetch(`${APP}${path}`);
        const target = join(FILM, "public", file);
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, Buffer.from(await response.arrayBuffer()));
      },
      shot: async (file) => {
        const { data } = await cdp("Page.captureScreenshot", { format: "png" });
        mkdirSync(join(FILM, "public/stills"), { recursive: true });
        writeFileSync(join(FILM, "public/stills", file), Buffer.from(data, "base64"));
      },
    };

    console.log(`recording '${name}'`);
    const extra = (await scene(take)) || {};
    await wait(500);
    const duration = now();
    recording = false;
    await cdp("Page.stopScreencast");
    socket.close();

    if (frames.length) {
      // Screencast timestamps share a clock with each other, not with ours: place frames by their own deltas.
      const first = frames[0].t;
      const lines = ["ffconcat version 1.0"];
      frames.forEach((frame, i) => {
        const next = i + 1 < frames.length ? frames[i + 1].t - first : Math.max(duration, frame.t - first + 0.5);
        lines.push(`file '${join(framesDir, frame.file)}'`, `duration ${Math.max(0.001, next - (frame.t - first)).toFixed(4)}`);
      });
      lines.push(`file '${join(framesDir, frames[frames.length - 1].file)}'`);
      writeFileSync(join(framesDir, "frames.ffconcat"), lines.join("\n"));
      const out = join(FILM, "public/takes", `${name}.mp4`);
      const encode = spawnSync(FFMPEG, ["-y", "-f", "concat", "-safe", "0", "-i", join(framesDir, "frames.ffconcat"),
        "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "13", "-preset", "medium", "-g", "15", "-movflags", "+faststart", out], { cwd: FILM, encoding: "utf8" });
      if (encode.status !== 0) throw new Error(`ffmpeg failed: ${encode.stderr.slice(-600)}`);
      writeFileSync(join(FILM, "public/takes", `${name}.json`), JSON.stringify({ scene: name, seconds: Number(duration.toFixed(3)), frames: frames.length, marks, ...extra }, null, 1));
      console.log(`  -> takes/${name}.mp4 (${duration.toFixed(1)} s, ${frames.length} screencast frames)`);
    }
  } finally {
    chrome.kill();
  }
}

for (const name of process.argv.slice(2)) await record(name);
