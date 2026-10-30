// Headless-Edge screenshot + console check of a bridge page.
//
// Renders a LOCAL working copy of configurator.html / builder.html /
// wallpaper/index.html through the RUNNING bridge (port 17320): the page
// request is intercepted and answered with the local file, every other
// request (/config, /health, /library, scripts) goes to the bridge. So a
// change can be looked at before a build replaces the installed bridge.
//
// Usage:
//   node tools/ui_shot.mjs --page configurator --out shot.png
//   node tools/ui_shot.mjs --page builder --file wallpaper_bridge/builder.html --out b.png
//   node tools/ui_shot.mjs --page "wallpaper?screen=0&shot=1" \
//        --file wallpaper_bridge/wallpaper/index.html --out w.png \
//        --eval "showStandbyCard(true,'noframes'); 1" --size 1600x400
//
// --eval runs after load (awaited if it returns a promise); its result is
// printed. Console errors and uncaught exceptions are printed at the end.
//
// Headless gotcha: the page's WebSocket to the bridge does not come up in
// headless Edge (same with the unchanged Configurator), so settings never
// arrive by push. Feed them in --eval instead, e.g. for the Configurator:
//   (async()=>{const c=await (await fetch('/config')).json();
//     _lastConfigSnapshot={screens:c.screens}; settings=c.screens[0];
//     setLanguage('de'); applyScreenCount(2); renderAll();
//     activateSectionTab('home'); return 'ok'})()
// A screenshot right after a scroll jump can show the page twice
// (compositor artefact) -- re-shoot before believing it.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith("--")) acc.push([a.slice(2), all[i + 1]]);
  return acc;
}, []));
const page = args.page || "configurator";
const out = args.out || "shot.png";
const [W, H] = (args.size || "1600x1000").split("x").map(Number);
const REPO = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const defaults = {
  configurator: "wallpaper_bridge/configurator.html",
  builder: "wallpaper_bridge/builder.html",
  wallpaper: "wallpaper_bridge/wallpaper/index.html",
};
const local = args.file || defaults[page.split("?")[0]];
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const PORT = 9335;
const prof = fs.mkdtempSync(path.join(os.tmpdir(), "ui-shot-"));
const proc = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${prof}`, `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let tabs;
for (let i = 0; i < 40 && !tabs; i++) {
  try { tabs = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); } catch { await sleep(250); }
}
const tab = tabs.find((t) => t.type === "page");
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pend = {};
const logs = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.method === "Fetch.requestPaused") {
    const body = fs.readFileSync(path.resolve(REPO, local)).toString("base64");
    ws.send(JSON.stringify({ id: 99999, method: "Fetch.fulfillRequest", params: {
      requestId: m.params.requestId, responseCode: 200,
      responseHeaders: [{ name: "Content-Type", value: "text/html; charset=utf-8" }], body } }));
  }
  if (m.method === "Runtime.exceptionThrown") {
    const d = m.params.exceptionDetails;
    logs.push("EXCEPTION " + String((d.exception && d.exception.description) || d.text).slice(0, 400));
  }
  if (m.method === "Runtime.consoleAPICalled" && /error|warn/.test(m.params.type)) {
    logs.push(m.params.type + " " + m.params.args.map((a) => a.value ?? a.description).join(" ").slice(0, 300));
  }
  if (m.id && pend[m.id]) { pend[m.id](m.result); delete pend[m.id]; }
};
const send = (method, params = {}) => new Promise((r) => {
  const i = ++id; pend[i] = r; ws.send(JSON.stringify({ id: i, method, params }));
});

await send("Runtime.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
if (local) {
  // Only the page document itself; "*/<page>*" would also catch
  // /wallpaper/glripple.js and serve it HTML.
  await send("Fetch.enable", { patterns: [{ urlPattern: `*/${page}`, requestStage: "Request" }] });
}
// Skip first-run wizard and both tours.
await send("Page.addScriptToEvaluateOnNewDocument", { source:
  "try{localStorage.setItem('cfg.firstRunDone','1');localStorage.setItem('cfg.tourDone','1');" +
  "localStorage.setItem('signalrgb.tour_seen','1');localStorage.setItem('signalrgb.builder.tour_seen','1');}catch(e){}" });
await send("Page.navigate", { url: `http://127.0.0.1:17320/${page}` });
await sleep(3500);
if (args.eval) {
  const r = await send("Runtime.evaluate", { expression: args.eval, returnByValue: true, awaitPromise: true });
  if (r.result && r.result.value !== undefined) console.log("eval:", JSON.stringify(r.result.value).slice(0, 2000));
  if (r.exceptionDetails) console.log("eval threw:", r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  await sleep(1200);
}
const shot = await send("Page.captureScreenshot", { format: "png" });
fs.writeFileSync(out, Buffer.from(shot.data, "base64"));
console.log("screenshot:", path.resolve(out));
console.log(logs.join("\n") || "(no console errors)");
ws.close();
proc.kill();
