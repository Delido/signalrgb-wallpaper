// Sensor skins (Ring / Bar / Graph) for cpu-meter, ram-meter, hardware-sensor.
//
// WHY THIS EXISTS
//
// v2.6.0 added three looks for the sensor widgets, modelled on two
// dashboard screenshots (donut gauge with the number in the middle,
// segmented slanted bar, area graph with a -1m / -30s / now axis). They
// plug into the existing skin mechanism (opts.skin), so the classic look
// stays the default and existing layouts do not change.
//
// The code under test is CUT OUT of the shipped page and executed in a
// node:vm context -- a model would keep passing if the page lost the
// behaviour it models.
//
// Also covered, because it surfaced while building this: the
// hardware-sensor sparkline has called drawSparkline() without a ceiling
// "to autoscale" since it was added, but drawSparkline never autoscaled.
// value / undefined is NaN, canvas ignores NaN coordinates, and the
// sensor sparkline was never drawn at all.
//
// The skin catalogue exists three times (wallpaper page, Configurator
// schema, bridge /widgets/skins) and is synced by hand; the first check
// group fails if they drift.
//
// Run: node tests/test_sensor_skins.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = readFileSync(join(ROOT, "wallpaper_bridge", "wallpaper", "index.html"), "utf8");
const CONF = readFileSync(join(ROOT, "wallpaper_bridge", "configurator.html"), "utf8");
const BRIDGE = readFileSync(join(ROOT, "wallpaper_bridge", "bridge.py"), "utf8");

let pass = 0, fail = 0;
function check(label, ok, detail = "") {
  if (ok) { pass++; console.error("  ok    " + label); }
  else { fail++; console.error("  FAIL  " + label + (detail ? "\n          " + detail : "")); }
}

// Brace-matched extraction: a fixed character window is how two earlier
// checks in this project ended up inspecting the wrong code.
function extractBlock(src, header) {
  const at = src.indexOf(header);
  if (at === -1) return "";
  const open = src.indexOf("{", at);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") { depth--; if (depth === 0) return src.slice(at, i + 1); }
  }
  return "";
}

// ── 1. the three catalogue copies agree ─────────────────────────────────
console.error("\nskin catalogue\n" + "=".repeat(68));
const pageList = /const SENSOR_SKIN_LIST = \[([\s\S]*?)\];/.exec(PAGE);
const confList = /const SENSOR_SKIN_OPTIONS = \[([\s\S]*?)\];/.exec(CONF);
const brList = /SENSOR_SKINS = \[([\s\S]*?)\]/.exec(BRIDGE);
const ids = (m, re) => m ? [...m[1].matchAll(re)].map((x) => x[1]) : [];
const pIds = ids(pageList, /id:\s*"(\w+)"/g);
const cIds = ids(confList, /value:\s*"(\w+)"/g);
const bIds = ids(brList, /"id":\s*"(\w+)"/g);
check("the page lists the skins", pIds.length === 4, pIds.join(","));
check("Configurator and page agree", cIds.join() === pIds.join(), `${cIds} vs ${pIds}`);
check("bridge and page agree", bIds.join() === pIds.join(), `${bIds} vs ${pIds}`);
const labels = (m, re) => m ? [...m[1].matchAll(re)].map((x) => x[1]) : [];
check("labels agree too",
      labels(pageList, /label:\s*"([^"]+)"/g).join() ===
      labels(confList, /label:\s*"([^"]+)"/g).join() &&
      labels(pageList, /label:\s*"([^"]+)"/g).join() ===
      labels(brList, /"label":\s*"([^"]+)"/g).join());
check("'default' is the classic look, listed first", pIds[0] === "default");
const mirror = extractBlock(PAGE, "const SKIN_CATALOG_MIRROR = {");
for (const t of ["cpu-meter", "ram-meter", "hardware-sensor"]) {
  check(`page mirror offers skins for ${t}`,
        new RegExp('"' + t + '":\\s*SENSOR_SKIN_LIST').test(mirror));
  check(`bridge /widgets/skins offers skins for ${t}`,
        new RegExp('"' + t + '":\\s*SENSOR_SKINS').test(BRIDGE));
  const schema = extractBlock(CONF, '  "' + t + '": {');
  check(`Configurator schema of ${t} has the picker`,
        /key:\s*"skin"[\s\S]{0,120}SENSOR_SKIN_OPTIONS/.test(schema));
  const reg = extractBlock(PAGE, 'WIDGET_REGISTRY["' + t + '"] = {');
  check(`${t} uses the shared skins`, /skins:\s*SENSOR_SKINS/.test(reg));
  check(`${t} exposes a reading()`, /reading:\s*\(/.test(reg));
  check(`${t} tick hands off to the skin first`,
        /tick:\s*\(rec\)\s*=>\s*\{\s*if \(_renderSensorSkin\(rec\)\) return;/.test(reg),
        "otherwise the classic markup's selectors run against skin markup");
}
check("every listed skin is implemented",
      pIds.filter((i) => i !== "default").every((i) =>
        new RegExp("\\n  " + i + ":\\s*\\{\\s*\\n\\s*markup:").test(
          extractBlock(PAGE, "const SENSOR_SKINS = {"))));
// const is not hoisted: v2.4.4-beta.7 shipped a page that died on load
// from exactly this.
check("SENSOR_SKINS is declared before the widgets use it",
      PAGE.indexOf("const SENSOR_SKINS = {") > 0 &&
      PAGE.indexOf("const SENSOR_SKINS = {") < PAGE.indexOf("skins: SENSOR_SKINS"));
check("SENSOR_SKIN_LIST is declared before the mirror uses it",
      PAGE.indexOf("const SENSOR_SKIN_LIST") < PAGE.indexOf("const SKIN_CATALOG_MIRROR"));

// ── 2. execute the shipped code ─────────────────────────────────────────
console.error("\nrendering (shipped code in node:vm)\n" + "=".repeat(68));

const skinsBlockStart = PAGE.indexOf("let _sgSeq = 0;");
const skinsBlockEnd = PAGE.indexOf('WIDGET_REGISTRY["cpu-meter"] = {');
const code = [
  extractBlock(PAGE, "function rgbToRgba("),
  extractBlock(PAGE, "function drawSparkline("),
  extractBlock(PAGE, "function _widgetSkinForOpts("),
  extractBlock(PAGE, "function _widgetActiveSkin("),
  PAGE.slice(skinsBlockStart, skinsBlockEnd),
  extractBlock(PAGE, 'WIDGET_REGISTRY["cpu-meter"] = {') + ";",
  extractBlock(PAGE, 'WIDGET_REGISTRY["ram-meter"] = {') + ";",
  extractBlock(PAGE, 'WIDGET_REGISTRY["hardware-sensor"] = {') + ";",
  "globalThis.__out = { SENSOR_SKINS, drawSparkline, drawAreaGraph, _sensorScale, _renderSensorSkin };",
].join("\n");

function recorder() {
  const ops = [];
  const ctx = new Proxy({ ops }, {
    get(t, k) {
      if (k === "ops") return ops;
      if (k === "createLinearGradient") return () => ({ addColorStop() {} });
      return (...a) => { ops.push([k, ...a]); };
    },
    set(t, k, v) { ops.push(["set:" + String(k), v]); return true; },
  });
  return ctx;
}

function fakeNode(ctx) {
  return {
    textContent: "", attrs: {}, style: {},
    classList: { set: new Set(),
      toggle(c, on) { on ? this.set.add(c) : this.set.delete(c); },
      contains(c) { return this.set.has(c); } },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    getContext() { return ctx; },
  };
}
function fakeWidget(type, opts, ctx) {
  const nodes = {};
  const el = {
    nodes,
    querySelector(sel) { return nodes[sel] || (nodes[sel] = fakeNode(ctx)); },
    querySelectorAll(sel) {
      return nodes[sel] || (nodes[sel] = Array.from({ length: 14 }, () => fakeNode(ctx)));
    },
  };
  return { el, type, opts, reg: null };
}

const ctx2d = recorder();
const sandbox = {
  WIDGET_REGISTRY: {},
  lastSysStats: null, sysstatsHistory: [], hwmonHistory: Object.create(null),
  currentTintCss: "rgb(255,0,0)",
  sizeCanvasToCss: () => ({ w: 200, h: 100, dpr: 1 }),
  getComputedStyle: () => ({ getPropertyValue: () => "#ff79c6" }),
  console,
};
vm.createContext(sandbox);
let ran = true;
try { vm.runInContext(code, sandbox); } catch (e) { ran = false; console.error(e); }
check("the extracted page code runs", ran && sandbox.__out);
const { SENSOR_SKINS, drawSparkline, _sensorScale, _renderSensorSkin } = sandbox.__out || {};
const REG = sandbox.WIDGET_REGISTRY;

function render(type, skin, opts = {}) {
  const rec = fakeWidget(type, { skin, ...opts }, ctx2d);
  rec.reg = REG[type];
  const handled = _renderSensorSkin(rec);
  return { rec, handled, n: rec.el.nodes };
}

// Ring
sandbox.lastSysStats = { cpu: 36, ram: 58 };
let r = render("cpu-meter", "ring");
check("a ring renders through the skin", r.handled === true);
check("36 % CPU -> arc covers 36 of 100",
      r.n[".sg-arc"].attrs["stroke-dasharray"] === "36.0 100",
      r.n[".sg-arc"].attrs["stroke-dasharray"]);
check("the number sits in the middle", r.n[".sg-value"].textContent === "36");
check("with its unit underneath", r.n[".sg-unit"].textContent === "%");
check("and the label on top", r.n[".sg-label"].textContent === "CPU");
sandbox.lastSysStats = { cpu: 0, ram: 0 };
r = render("cpu-meter", "ring");
check("0 % hides the arc (a round cap would still draw a dot)",
      r.n[".sg-arc"].style.display === "none");
sandbox.lastSysStats = { cpu: 140, ram: 0 };
r = render("cpu-meter", "ring");
check("values past the scale clamp to a full ring",
      r.n[".sg-arc"].attrs["stroke-dasharray"] === "100.0 100");
sandbox.lastSysStats = null;
r = render("ram-meter", "ring");
check("no data yet -> a dash, not NaN", r.n[".sg-value"].textContent === "—");

// The SignalRGB sensor case: real scale from the sensor itself.
sandbox.lastSysStats = { hwmon: { "SignalRGB / Corsair / Pump":
  { value: 2789, unit: "RPM", min: 0, max: 3000, source: "signalrgb" } } };
r = render("hardware-sensor", "ring", { sensorPath: "SignalRGB / Corsair / Pump", decimals: 0 });
check("a pump at 2789 of 3000 RPM fills 93 %",
      r.n[".sg-arc"].attrs["stroke-dasharray"] === "93.0 100",
      r.n[".sg-arc"].attrs["stroke-dasharray"]);
check("four-digit readings step the font down to fit the ring",
      r.n[".sg-value"].attrs["font-size"] === "22", r.n[".sg-value"].attrs["font-size"]);
check("the label is the sensor's leaf name", r.n[".sg-label"].textContent === "Pump");

// Two rings on one page must not share a gradient id (the second would
// render with the first one's gradient, or none).
const m1 = SENSOR_SKINS.ring.markup(), m2 = SENSOR_SKINS.ring.markup();
const gid = (m) => (/linearGradient id="([^"]+)"/.exec(m) || [])[1];
check("every ring gets its own gradient id", gid(m1) && gid(m1) !== gid(m2));
check("the arc references its own gradient", m1.includes('stroke="url(#' + gid(m1) + ')"'));
check("pathLength=100 is what makes the dash a percentage",
      /class="sg-arc"[^>]*pathLength="100"/.test(m1));

// Scale precedence.
check("an explicit maximum wins", _sensorScale({ min: 0, max: 3000 }, "RPM", [], 2000)[1] === 2000);
check("then the sensor's own range",
      _sensorScale({ min: 0, max: 3000, value: 10 }, "RPM", [], "")[1] === 3000);
check("% defaults to 0-100", _sensorScale({ value: 40 }, "%", [], "")[1] === 100);
check("°C defaults to 0-100", _sensorScale({ value: 61 }, "°C", [], "")[1] === 100);
check("anything else scales off the recent peak",
      _sensorScale({ value: 5 }, "W", [80, 120, 100], "")[1] === 150);
check("a blank / zero maximum means automatic",
      _sensorScale({ value: 40 }, "%", [], 0)[1] === 100);

// Bar
sandbox.lastSysStats = { cpu: 50, ram: 0 };
r = render("cpu-meter", "bar");
const lit = r.n[".sg-bar i"].filter((s) => s.classList.contains("on")).length;
check("50 % lights 7 of 14 segments", lit === 7, String(lit));
const bm = SENSOR_SKINS.bar.markup();
check("the bar markup has one segment per step", (bm.match(/<i /g) || []).length === 14);

// Graph
sandbox.sysstatsHistory = Array.from({ length: 30 }, (_, i) => ({ cpu: i, ram: 0 }));
sandbox.lastSysStats = { cpu: 29, ram: 0 };
ctx2d.ops.length = 0;
r = render("cpu-meter", "graph");
check("the graph header shows the current value", r.n[".sg-now"].textContent === "29 %",
      r.n[".sg-now"].textContent);
const lines = ctx2d.ops.filter((o) => o[0] === "lineTo" || o[0] === "moveTo");
const firstData = ctx2d.ops.findIndex((o) => o[0] === "set:lineWidth" && o[1] === 1.8);
const dataMoves = ctx2d.ops.slice(0, firstData).filter((o) => o[0] === "moveTo");
const firstX = dataMoves.length ? dataMoves[dataMoves.length - 1][1] : -1;
check("a half-full buffer starts mid-axis, so -1m / -30s stay true",
      firstX > 22 + 60 && firstX < 22 + 100, `first x=${firstX}`);
check("all plotted coordinates are finite",
      lines.every((o) => Number.isFinite(o[1]) && Number.isFinite(o[2])));
sandbox.sysstatsHistory = Array.from({ length: 120 }, () => ({ cpu: 5, ram: 0 }));
ctx2d.ops.length = 0;
render("cpu-meter", "graph");
// The data path is everything between the end of the dashed grid
// (setLineDash([])) and the stroke width of the value line.
const gridEnd = ctx2d.ops.findIndex((o) => o[0] === "setLineDash" && o[1].length === 0);
const lineW = ctx2d.ops.findIndex((o) => o[0] === "set:lineWidth" && o[1] === 1.8);
const pathOps = ctx2d.ops.slice(gridEnd, lineW).filter((o) => o[0] === "moveTo" || o[0] === "lineTo");
check("only the last minute is plotted (120 samples in the buffer)",
      pathOps.length === 60, String(pathOps.length));

// Default skin: untouched.
r = render("cpu-meter", undefined);
check("no skin -> the classic path runs, not a skin", r.handled === false);
r = render("cpu-meter", "default");
check("'default' -> classic as well", r.handled === false);

// The sparkline fix.
ctx2d.ops.length = 0;
drawSparkline({ getContext: () => ctx2d }, [50, 60, 70], "rgb(1,2,3)");
const sp = ctx2d.ops.filter((o) => o[0] === "lineTo" || o[0] === "moveTo");
check("drawSparkline without a ceiling now autoscales",
      sp.length >= 3 && sp.every((o) => Number.isFinite(o[2])),
      "value / undefined = NaN -- the hardware-sensor sparkline was never drawn");
ctx2d.ops.length = 0;
drawSparkline({ getContext: () => ctx2d }, [50, 60], "rgb(1,2,3)", 100);
const y60 = ctx2d.ops.filter((o) => o[0] === "lineTo")[0][2];
check("an explicit ceiling is still respected", Math.abs(y60 - 40) < 1e-6, String(y60));

// ── 3. perf rules ───────────────────────────────────────────────────────
console.error("\nperformance rules\n" + "=".repeat(68));
const skinsSrc = PAGE.slice(skinsBlockStart, skinsBlockEnd);
check("no requestAnimationFrame in the skins", !/requestAnimationFrame/.test(skinsSrc));
const cssStart = PAGE.indexOf("v2.6.0: sensor skins (ring / bar / graph)");
const css = PAGE.slice(cssStart, PAGE.indexOf(".widget-net-graph .stat-pair {", cssStart));
check("the skin CSS was located", css.length > 400, String(css.length));
check("no CSS transition on values that change every tick", !/transition\s*:/.test(css),
      "transitions on per-tick values were once 85 % of GPU load");
check("no color-mix() (Wallpaper Engine's Chromium may not have it)",
      !/color-mix\(/.test(css) && !/color-mix\(/.test(skinsSrc));

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
