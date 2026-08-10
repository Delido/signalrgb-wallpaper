// Shared machinery for running the two preset tables for real.
//
// test_preset_parity.mjs originally compared the tables with regexes over
// the source. That worked for the two presets whose alpha happens to be a
// literal (`const a = 0.34`) and silently gave up on the other thirteen,
// which compute it — `a: 0.5 + Math.random()*0.3` is not something a
// regex can evaluate. Those thirteen counted as passes, so the suite
// reported 16/16 green while measuring under a quarter of the surface.
//
// Both tables have the same shape — targetCount / spawn / step / render,
// plus optional before/after hooks — so instead of reading the source we
// extract each table, eval it against a tiny recording canvas, and look
// at what it actually paints. No browser, no dependencies: the presets
// only ever touch a small, fixed slice of the 2D context.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
export const repo = join(here, "..");

export const CFG = readFileSync(join(repo, "wallpaper_bridge", "configurator.html"), "utf8");
export const WP = readFileSync(join(repo, "wallpaper_bridge", "wallpaper", "index.html"), "utf8");

/** Every ambient preset the Configurator offers, minus "off". */
export function presetNames() {
  const m = CFG.match(/const AMBIENT_PRESETS = \[(.*?)\];/s);
  if (!m) throw new Error("AMBIENT_PRESETS name list not found in configurator.html");
  return m[1].split(",").map((s) => s.trim().replace(/^"|"$/g, "")).filter((s) => s && s !== "off");
}

/**
 * Slice out a `const <name> = { ... }` initialiser by brace depth.
 *
 * Depth counting rather than a terminator search: the tables contain
 * nested objects, and `waves` legitimately holds a `}` inside a template
 * literal. Strings and comments are skipped so those don't shift depth.
 */
export function extractTable(src, varName) {
  const start = src.indexOf(`const ${varName} = {`);
  if (start === -1) throw new Error(`${varName} not found`);
  let i = src.indexOf("{", start);
  let depth = 0;
  for (; i < src.length; i++) {
    const c = src[i];
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i === -1) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i) + 1; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const q = c;
      for (i++; i < src.length; i++) {
        if (src[i] === "\\") { i++; continue; }
        if (src[i] === q) break;
        // `${...}` can nest braces, but they're balanced, so ignoring
        // the whole literal keeps the count right either way.
      }
      continue;
    }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return src.slice(src.indexOf("{", start), i + 1); }
  }
  throw new Error(`unterminated ${varName}`);
}

/** A 2D context that records what was drawn instead of rasterising it. */
export function recordingCtx(w, h) {
  const ops = [];
  let path = [];
  const st = { globalAlpha: 1, fillStyle: "#000", strokeStyle: "#000", lineWidth: 1,
               globalCompositeOperation: "source-over", font: "10px sans-serif",
               shadowBlur: 0, shadowColor: "transparent", lineCap: "butt", lineJoin: "miter",
               filter: "none", textAlign: "start", textBaseline: "alphabetic" };
  const stack = [];

  const grad = () => ({ stops: [], addColorStop(o, c) { this.stops.push([o, c]); } });

  const ctx = {
    canvas: { width: w, height: h },
    ...st,
    save() { stack.push({ ...pick() }); },
    restore() { const s = stack.pop(); if (s) Object.assign(ctx, s); },
    beginPath() { path = []; },
    closePath() {},
    moveTo(x, y) { path.push([x, y]); },
    lineTo(x, y) { path.push([x, y]); },
    bezierCurveTo(a, b, c, d, x, y) { path.push([x, y]); },
    quadraticCurveTo(a, b, x, y) { path.push([x, y]); },
    arc(x, y, r) { ops.push({ op: "arc", x, y, r, ...pick() }); path.push([x, y]); },
    arcTo() {},
    ellipse(x, y, rx, ry) { ops.push({ op: "arc", x, y, r: Math.max(rx, ry), ...pick() }); },
    rect(x, y, rw, rh) { path.push([x, y]); ops.push({ op: "rect", x, y, w: rw, h: rh, ...pick() }); },
    fill() { ops.push({ op: "fill", path: path.slice(), ...pick() }); },
    stroke() { ops.push({ op: "stroke", path: path.slice(), ...pick() }); },
    clip() {},
    fillRect(x, y, rw, rh) { ops.push({ op: "fillRect", x, y, w: rw, h: rh, ...pick() }); },
    strokeRect(x, y, rw, rh) { ops.push({ op: "strokeRect", x, y, w: rw, h: rh, ...pick() }); },
    clearRect() { ops.push({ op: "clear" }); },
    fillText(t, x, y) { ops.push({ op: "text", text: String(t), x, y, ...pick() }); },
    strokeText(t, x, y) { ops.push({ op: "text", text: String(t), x, y, ...pick() }); },
    measureText(t) { return { width: String(t).length * 6 }; },
    createLinearGradient() { return grad(); },
    createRadialGradient() { return grad(); },
    createPattern() { return null; },
    drawImage() { ops.push({ op: "image", ...pick() }); },
    setTransform() {}, resetTransform() {}, transform() {},
    translate() {}, rotate() {}, scale() {},
    getTransform() { return { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }; },
    setLineDash() {}, getLineDash() { return []; },
    getImageData(x, y, gw, gh) {
      return { width: gw, height: gh, data: new Uint8ClampedArray(gw * gh * 4) };
    },
    putImageData() {},
    createImageData(gw, gh) {
      return { width: gw, height: gh, data: new Uint8ClampedArray(gw * gh * 4) };
    },
    ops,
  };
  function pick() {
    return {
      globalAlpha: ctx.globalAlpha, fillStyle: ctx.fillStyle, strokeStyle: ctx.strokeStyle,
      lineWidth: ctx.lineWidth, globalCompositeOperation: ctx.globalCompositeOperation,
      shadowBlur: ctx.shadowBlur, font: ctx.font, filter: ctx.filter,
    };
  }
  return ctx;
}

/**
 * Alpha carried by a colour string.
 *
 * Handles rgba(), hsla() and #rrggbbaa. Missing hsla() here is not a
 * cosmetic gap: aurora and plasma paint exclusively in hsla(), so an
 * rgba-only reader falls through to the opaque default and reports
 * peak 1.0 for an effect that is in fact painting at 0.0014 — which is
 * precisely the bug this suite is supposed to detect.
 */
function colourAlpha(style) {
  if (typeof style !== "string") return null;
  let m = style.match(/rgba\(\s*[\d.]+\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*([\d.eE+-]+)\s*\)/);
  if (m) return parseFloat(m[1]);
  m = style.match(/hsla\(\s*[\d.eE+-]+\s*,\s*[\d.]+%\s*,\s*[\d.]+%\s*,\s*([\d.eE+-]+)\s*\)/);
  if (m) return parseFloat(m[1]);
  if (/^#[0-9a-f]{8}$/i.test(style)) return parseInt(style.slice(7, 9), 16) / 255;
  return null;
}

/** Alpha actually applied to a draw: globalAlpha x any alpha in the colour. */
export function effectiveAlpha(op) {
  const ga = typeof op.globalAlpha === "number" ? op.globalAlpha : 1;
  const style = op.op === "stroke" || op.op === "strokeRect" ? op.strokeStyle : op.fillStyle;
  let ca = 1;
  if (typeof style === "string") {
    const a = colourAlpha(style);
    if (a !== null) ca = a;
  } else if (style && Array.isArray(style.stops)) {
    // A gradient's peak is the strongest stop it defines.
    ca = 0;
    for (const [, c] of style.stops) {
      const a = colourAlpha(String(c));
      ca = Math.max(ca, a === null ? 1 : a);
    }
    if (!style.stops.length) ca = 1;
  }
  return ga * ca;
}

/** Approximate area in px^2 that a recorded draw covers. */
export function opArea(op, w, h) {
  switch (op.op) {
    case "arc":     return Math.PI * op.r * op.r;
    case "fillRect":
    case "rect":
    case "strokeRect": return Math.abs((op.w || 0) * (op.h || 0));
    case "text":    return (op.text ? op.text.length : 0) * 100;
    case "stroke": {
      if (!op.path || op.path.length < 2) return 0;
      let len = 0;
      for (let i = 1; i < op.path.length; i++) {
        len += Math.hypot(op.path[i][0] - op.path[i - 1][0], op.path[i][1] - op.path[i - 1][1]);
      }
      return len * Math.max(1, op.lineWidth || 1);
    }
    case "fill": {
      // Bounding box of the path is a coarse but stable proxy.
      if (!op.path || !op.path.length) return 0;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const [x, y] of op.path) {
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
      return Math.max(0, (x1 - x0)) * Math.max(0, (y1 - y0));
    }
    default: return 0;
  }
}

/**
 * Run one preset for a while and report what it painted.
 *
 * Mirrors the real driver loops rather than approximating them. The two
 * sides differ in ways that matter:
 *
 *   wallpaper  targetCount(density, w, h)  tint = CSS string or null
 *              optional respawn() + renderAll(ctx, particles, tint)
 *   tile       targetCount(w, h)           render(ctx, p, particles)
 *
 * Getting this wrong is not a harmless mismatch: calling the wallpaper's
 * `targetCount` with two arguments makes `h` undefined, the target comes
 * out NaN, every particle is culled on the first frame and the preset
 * records zero draws — which reads exactly like a dead effect.
 *
 * Deterministic: Math.random is replaced by a seeded LCG so a preset that
 * spawns rarely still behaves identically run to run. Without this, a
 * threshold check on a sparse effect like `lightning` would flake.
 */
export function runPreset(table, name, opts = {}) {
  const {
    w = 1920, h = 1080, frames = 90, seed = 12345,
    kind = "wallpaper", density = 1, tint = null,
  } = opts;
  const def = table[name];
  if (!def) throw new Error(`preset ${name} missing`);

  const realRandom = Math.random;
  let s = seed >>> 0;
  Math.random = () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };

  const wallpaper = kind === "wallpaper";
  const targetOf = () => {
    const n = wallpaper ? def.targetCount(density, w, h) : def.targetCount(w, h);
    return Number.isFinite(n) ? Math.max(0, Math.min(20000, Math.round(n))) : 0;
  };

  try {
    const ctx = recordingCtx(w, h);
    let particles = [];
    const dt = 1 / 60;

    for (let f = 0; f < frames; f++) {
      const target = targetOf();
      while (particles.length > target) particles.pop();
      let guard = 0;
      while (particles.length < target && guard++ < 20000) particles.push(def.spawn(w, h));
      for (let i = particles.length - 1; i >= 0; i--) {
        if (!def.step(particles[i], dt, w, h)) {
          particles[i] = particles[particles.length - 1];
          particles.pop();
        }
      }
      if (typeof def.before === "function") def.before(ctx, tint, w, h);
      if (wallpaper && typeof def.renderAll === "function") {
        def.renderAll(ctx, particles, tint);
      } else {
        for (const p of particles) def.render(ctx, p, tint, particles);
      }
      if (typeof def.after === "function") def.after(ctx, particles, tint, w, h);
    }

    const draws = ctx.ops.filter((o) => o.op !== "clear");

    // `arc` and the `fill` that commits it are recorded as two ops, so
    // counting both would double every circular preset's coverage.
    const forArea = draws.filter((o, i) =>
      !(o.op === "fill" && i > 0 && draws[i - 1].op === "arc"));

    let ink = 0;
    for (const o of forArea) ink += effectiveAlpha(o) * opArea(o, w, h);

    // Loop, not Math.max(...draws): a dense preset like starfield records
    // hundreds of thousands of ops over a long run and spreading those as
    // arguments overflows the call stack.
    let peak = 0;
    for (const o of draws) {
      const a = effectiveAlpha(o);
      if (a > peak) peak = a;
    }

    return {
      ops: draws,
      particles: particles.length,
      // Peak alpha of a single draw. Useful, but on its own a poor
      // visibility signal: one opaque gradient stop pins it at 1.0 while
      // the effect covers almost nothing.
      peakAlpha: peak,
      // What the eye actually integrates: alpha x area per frame, as a
      // fraction of the viewport. This is the number that moved when
      // aurora went from invisible to visible.
      coverage: ink / frames / (w * h),
      target: targetOf(),
    };
  } finally {
    Math.random = realRandom;
  }
}

/**
 * Lift a top-level `function name(...) {...}` out of the source verbatim.
 *
 * Deliberately re-used rather than reimplemented: a hand-written stub of
 * rgbToRgba in this file would be a third copy of the very thing whose
 * divergence this suite exists to catch, and it would have hidden the
 * v2.4.4-beta.1 bug (hex input silently ignored) instead of exposing it.
 */
export function extractFunction(src, name) {
  const m = new RegExp(`(^|\\n)function ${name}\\s*\\(`).exec(src);
  if (!m) return null;
  const start = m.index + (m[1] ? 1 : 0);
  let i = src.indexOf("{", start);
  let depth = 0;
  for (; i < src.length; i++) {
    const c = src[i];
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i === -1) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i) + 1; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const q = c;
      for (i++; i < src.length; i++) {
        if (src[i] === "\\") { i++; continue; }
        if (src[i] === q) break;
      }
      continue;
    }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  return null;
}

/**
 * Lift a top-level `const NAME = ...;` declaration out verbatim, ending
 * at the first semicolon that is not inside a string or comment.
 */
export function extractDeclaration(src, name) {
  const m = new RegExp(`(^|\\n)(const|let|var) ${name}\\s*=`).exec(src);
  if (!m) return null;
  const start = m.index + (m[1] ? 1 : 0);
  for (let i = src.indexOf("=", start); i < src.length; i++) {
    const c = src[i];
    if (c === "/" && src[i + 1] === "/") { i = src.indexOf("\n", i); if (i === -1) break; continue; }
    if (c === "/" && src[i + 1] === "*") { i = src.indexOf("*/", i) + 1; continue; }
    if (c === '"' || c === "'" || c === "`") {
      const q = c;
      for (i++; i < src.length; i++) {
        if (src[i] === "\\") { i++; continue; }
        if (src[i] === q) break;
      }
      continue;
    }
    if (c === ";") return src.slice(start, i + 1);
  }
  return null;
}

/** Instantiate a preset table in isolation, with the helpers it expects. */
export function loadTable(src, varName, extraPrelude = "") {
  const body = extractTable(src, varName);

  // Real helpers where they exist in the file, stubs only for the ones
  // that genuinely belong to the host page (quality buckets, cursor).
  const borrowed = ["rgbToRgba"]
    .map((n) => extractFunction(src, n))
    .filter(Boolean)
    .join("\n");

  // Matrix's glyph pool lives above the table, spans several lines as a
  // `+`-joined literal, and contains a `;` *inside* one of the strings —
  // so scan for the terminator with string awareness instead of matching
  // to the first semicolon.
  // The storm preset keeps its strike timing in module-scope `_storm*`
  // variables. Rather than guessing their names one failure at a time,
  // take every such declaration from the source as written.
  const stormState = [...src.matchAll(/(?:^|\n)(?:let|var|const) (_storm\w*)\s*=/g)]
    .map((m) => extractDeclaration(src, m[1]))
    .filter(Boolean)
    .join("\n");

  const charset = extractDeclaration(src, "MATRIX_CHARSET");
  const matrix = charset
    ? `${charset}
       const MATRIX_CHARS = Array.from(MATRIX_CHARSET);
       const MATRIX_CHARS_LEN = MATRIX_CHARS.length;`
    : "";

  const prelude = `
    const _AMBIENT_REF_AREA = 1920 * 1080;
    function _ambientRadiusScale(w, h) {
      if (!w || !h) return 1;
      return Math.max(1, Math.min(3, Math.sqrt((w * h) / _AMBIENT_REF_AREA)));
    }
    function _ambientCountScale(w, h) {
      if (!w || !h) return 1;
      return Math.max(1, Math.min(4, (w * h) / _AMBIENT_REF_AREA));
    }
    function _qualityScale() { return 0.5; }
    function _qualityDpr() { return 1; }
    function _wormholeAnchorX(w) { return w / 2; }
    function _wormholeAnchorY(h) { return h / 2; }
    const TAU = Math.PI * 2;
    let _wormholeDiagTs = 0;
    let _cursorX = 0, _cursorY = 0;
    const window = { devicePixelRatio: 1 };
    ${stormState}
    ${borrowed}
    ${matrix}
    ${extraPrelude}
  `;
  // storm delegates to its sibling presets by name, so the table has to
  // be reachable under the identifier the source uses.
  const fn = new Function(`${prelude}\nconst ${varName} = ${body};\nreturn ${varName};`);
  return fn();
}
