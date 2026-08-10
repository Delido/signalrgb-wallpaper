// Static checks against the real wallpaper/index.html.
//
// test_standby_card.mjs models the connect()/standby logic and proves the
// model is correct. This file guards the other half: that the shipped page
// actually contains that logic. Without it, someone could refactor the
// guards out of index.html and the model tests would still pass happily.
//
// Deliberately shallow — regex over source, no DOM. It answers "is the
// protection still wired in", not "does it behave correctly".
//
// Run: node tests/test_wallpaper_source.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { execFileSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..");
const INDEX = join(repo, "wallpaper_bridge", "wallpaper", "index.html");

const src = readFileSync(INDEX, "utf8");
const results = { passed: 0, failed: [] };

function check(label, cond, detail = "") {
  if (cond) {
    results.passed++;
    console.log(`  PASS  ${label}`);
  } else {
    results.failed.push(label);
    console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`);
  }
}

console.log("\nissue #2 protections present in index.html");

check("previous socket's handlers are detached in connect()",
      /ws\.onopen\s*=\s*ws\.onclose\s*=\s*ws\.onerror\s*=\s*ws\.onmessage\s*=\s*null/.test(src));

const guardCount = (src.match(/sock\s*!==\s*ws/g) || []).length;
check("handlers are guarded against superseded sockets (>=3 guards)",
      guardCount >= 3, `found ${guardCount}`);

check("standby reconciler runs on an interval",
      /const\s+STANDBY_RECONCILE_MS\s*=\s*\d+/.test(src) &&
      /\}\s*,\s*STANDBY_RECONCILE_MS\s*\)/.test(src));

check("reconciler compares against readyState, not events",
      /readyState\s*===\s*1/.test(src));

check("sleep/resume detection resets the backoff",
      /_RESUME_JUMP_MS/.test(src) &&
      /_reconnectMs\s*=\s*RECONNECT_MS_MIN/.test(src));

console.log("\ndeclaration order (temporal dead zone)");
{
  // `let ws` and connect() must be declared before the resume detector's
  // interval body can reference them. An earlier draft of the fix placed
  // the detector above `let ws`, which would throw on the first tick.
  const wsDecl = src.indexOf("let ws = null");
  const resumeTick = src.indexOf("_RESUME_TICK_MS");
  check("resume detector is declared after `let ws`",
        wsDecl !== -1 && resumeTick !== -1 && resumeTick > wsDecl,
        `let ws @${wsDecl}, resume detector @${resumeTick}`);
}

console.log("\nJS parses");
{
  // Extract the largest inline <script> and hand it to node --check.
  const blocks = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  const biggest = blocks.sort((a, b) => b.length - a.length)[0] || "";
  check("found an inline script block", biggest.length > 1000,
        `largest block: ${biggest.length} chars`);
  const tmp = join(process.env.TEMP || "/tmp", `wp-syntax-${process.pid}.js`);
  try {
    const { writeFileSync, unlinkSync } = await import("node:fs");
    writeFileSync(tmp, biggest, "utf8");
    execFileSync(process.execPath, ["--check", tmp], { stdio: "pipe" });
    check("wallpaper JS parses without syntax errors", true);
    unlinkSync(tmp);
  } catch (e) {
    check("wallpaper JS parses without syntax errors", false,
          String(e.stderr || e).split("\n").slice(0, 3).join(" "));
  }
}

console.log("\nJS runs — top-level init completes without throwing");
{
  // Parsing is not enough. v2.4.4-beta.7 shipped a page that parsed
  // perfectly and was dead on arrival: removing the canvas-prescale
  // block took `let gridRenderer = "dom"` with it, because the
  // declaration had ended up inside the region being cut. Every
  // `gridRenderer === "canvas"` test then read an undeclared name,
  // which under "use strict" is a ReferenceError — thrown during init
  // from _syncGridCanvasVisibility, before the page ever opened its
  // WebSocket. Users got a black screen with the "bridge offline" card,
  // and every existing check still passed: the file parsed, the guards
  // were all present, the regexes all matched.
  //
  // So run it. The script only touches a narrow, predictable slice of
  // the browser API at module scope, which a Proxy-based stub covers.
  // This does not prove the page renders correctly — it proves top-level
  // initialisation reaches the end, which is exactly what was broken.
  const blocks = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  const biggest = blocks.sort((a, b) => b.length - a.length)[0] || "";
  const vm = await import("node:vm");

  const stub = () => new Proxy(function () {}, {
    get: (t, k) => {
      if (k === "length") return 0;
      if (k === Symbol.toPrimitive) return () => "";
      if (k === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      if (k === "style") return new Proxy({}, { get: () => () => {}, set: () => true });
      if (k === "then") return undefined;   // must not look thenable
      return stub();
    },
    apply: () => stub(),
    construct: () => stub(),
    set: () => true,
  });

  const ctx = {
    console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
    setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {},
    requestAnimationFrame: () => 0, cancelAnimationFrame() {},
    performance: { now: () => 0 },
    Date, Math, JSON, Intl, Promise, URLSearchParams, URL, TextEncoder, TextDecoder,
    document: stub(), window: stub(),
    navigator: { userAgent: "test", language: "en" },
    location: { search: "?screen=0", href: "http://127.0.0.1:17320/wallpaper/?screen=0",
                hostname: "127.0.0.1" },
    WebSocket: function () { return stub(); },
    Image: function () { return stub(); },
    localStorage: stub(), sessionStorage: stub(),
    fetch: () => Promise.resolve(stub()),
    ResizeObserver: function () { return stub(); },
    MutationObserver: function () { return stub(); },
    IntersectionObserver: function () { return stub(); },
    getComputedStyle: () => stub(),
    AudioContext: function () { return stub(); },
    CustomEvent: function () { return stub(); },
    Event: function () { return stub(); },
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    devicePixelRatio: 1, innerWidth: 1920, innerHeight: 1080,
  };
  ctx.globalThis = ctx;
  ctx.self = ctx;

  let initError = null;
  try {
    vm.runInNewContext(biggest, vm.createContext(ctx), { timeout: 10000 });
  } catch (e) {
    initError = `${e.constructor.name}: ${e.message}`.slice(0, 140);
  }
  check("top-level script runs to completion", initError === null, initError || "");

  // The specific name that went missing, called out so a failure points
  // straight at it rather than at a generic ReferenceError.
  check("gridRenderer is declared", /^\s*let gridRenderer\s*=/m.test(src));
}

console.log("\nversion stamping");
{
  const bridgePy = readFileSync(join(repo, "wallpaper_bridge", "bridge.py"), "utf8");
  const wpVer = bridgePy.match(/^WALLPAPER_VERSION\s*=\s*"([^"]+)"/m)?.[1];
  check("bridge.py declares WALLPAPER_VERSION", !!wpVer, `got ${wpVer}`);
  check("index.html declares a WALLPAPER_VERSION constant",
        /WALLPAPER_VERSION\s*=/.test(src));
}

console.log("\nno effect claims to be Lively-only any more");
{
  // History, because the labelling was wrong twice in different ways:
  //
  //   * hover-glow carried the badge on the claim that WE renders
  //     createRadialGradient as an opaque disc. It did look like that,
  //     but the cause was rgbToRgba() passing the default hex tint
  //     through unconverted — a bug on every host, not a WE quirk.
  //   * water and Liquid Distortion carried it because feImage yields
  //     nothing in WE's CEF (measured: 100 % transparent output). True
  //     at the time; they now render through the WebGL path instead and
  //     were confirmed working in WE.
  //
  // So the expected state is: no badges at all. This test fails if one
  // reappears without the picker's explainer hint coming back with it —
  // a lone badge with nothing explaining it is worse than none.
  const cfg = readFileSync(join(repo, "wallpaper_bridge", "configurator.html"), "utf8");

  const flagged = [...cfg.matchAll(/\{\s*value:\s*"([a-z-]+)"[\s\S]{0,260}?livelyOnly:\s*true/g)]
    .map((m) => m[1]);
  check("no pixelfx mode carries livelyOnly", flagged.length === 0,
        `flagged: [${flagged.join(", ")}]`);

  // Liquid Distortion's badge was hardcoded in the mousefx markup rather
  // than driven by the flag, so it needs its own check.
  const mousefxBadges = [...cfg.matchAll(/data-fx="([a-z]+)"[\s\S]{0,300}?fx-tile-badge/g)]
    .map((m) => m[1]);
  check("no mousefx tile carries a badge", mousefxBadges.length === 0,
        `badged: [${mousefxBadges.join(", ")}]`);

  // The badge markup and its translations stay in the file so a future
  // host-specific effect can use them; only the CSS rule and the keys
  // should survive, not an active badge.
  check("badge styling is still available for future use",
        /\.fx-tile-badge\s*\{/.test(cfg));
  check("badge translation keys retained",
        /"fx\.lively_only"/.test(cfg));
}

console.log("\npaused wallpaper stops waking the compositor");
{
  // The rAF probe exists to notice host-side render suspension. It ran at
  // a fixed ~5 Hz, which is fine while the wallpaper is live — but an
  // externally paused wallpaper (bridge fullscreen-watcher, game in the
  // foreground) usually is NOT suspended by the host, so the page kept
  // requesting frames and the Desktop Window Manager kept re-compositing.
  // Reported as ~2 % DWM CPU while gaming, i.e. the load pausing was
  // meant to remove.
  check("probe interval backs off while paused",
        /RAF_PROBE_MS_PAUSED\s*=\s*(\d+)/.test(src));
  const activeMs = Number(src.match(/RAF_PROBE_MS_ACTIVE\s*=\s*(\d+)/)?.[1] || 0);
  const pausedMs = Number(src.match(/RAF_PROBE_MS_PAUSED\s*=\s*(\d+)/)?.[1] || 0);
  check("paused cadence is much slower than active",
        pausedMs >= activeMs * 5, `active=${activeMs} paused=${pausedMs}`);
  check("the loop actually picks the interval by pause state",
        /isPaused\s*\?\s*RAF_PROBE_MS_PAUSED\s*:\s*RAF_PROBE_MS_ACTIVE/.test(src));

  // The staleness threshold must key off the cadence the PENDING frame
  // request was scheduled at — not off isPaused.
  //
  // They differ exactly when it matters. Wallpaper Engine's own tray-menu
  // pause stalls the frame loop (confirmed by measurement: rAF gap of
  // 20.5 s while setInterval kept ticking), and a stalled loop schedules
  // nothing new, so the pending request still carries the fast cadence
  // and its strict threshold — which is what keeps the stall detectable.
  // Keying off isPaused instead relaxed the threshold the instant we
  // paused, the stalled loop then looked healthy, and the page un-paused
  // itself in a loop.
  check("threshold keys off the pending cadence, not isPaused",
        /_rafProbePendingGap/.test(src) &&
        !/const limit\s*=\s*isPaused\s*\?/.test(src));
  check("the pending cadence is recorded where a frame arrives",
        /_lastRafTickMs\s*=\s*performance\.now\(\);[\s\S]{0,400}?_rafProbePendingGap\s*=\s*isPaused\s*\?/.test(src));

  // The two directions need opposite handling, and getting either wrong
  // was visible to users:
  //   pausing  — grace only. Refreshing the timestamp fakes a frame that
  //              never arrived, which made WE's menu pause oscillate.
  //   resuming — refresh and drop the grace. Leaving the stale timestamp
  //              made the probe re-pause ~2 s after un-pausing in Lively.
  const helper = src.match(/function _rafProbeOnPauseChange\(\)[\s\S]{0,2200}?\n\}/);
  check("pause-change helper found", !!helper);
  if (helper) {
    const body = helper[0];
    const pausingBranch = body.slice(0, body.indexOf("// RESUMING"));
    check("pausing branch does NOT refresh the timestamp",
          !/_lastRafTickMs\s*=/.test(pausingBranch), pausingBranch.trim().slice(0, 120));
    check("pausing branch sets a grace window",
          /_rafProbeGraceUntil\s*=\s*now\s*\+/.test(pausingBranch));
    const resumingBranch = body.slice(body.indexOf("// RESUMING"));
    check("resuming branch refreshes the timestamp",
          /_lastRafTickMs\s*=\s*now/.test(resumingBranch));
    check("resuming branch clears the grace window",
          /_rafProbeGraceUntil\s*=\s*0/.test(resumingBranch));
  }

  // The WebGL overlay is a compositor surface like the other canvases,
  // so it belongs in the paused-glow hide list.
  check("glripple canvas is hidden while paused",
        /body\.paused-glow #glripple-canvas/.test(src));
  check("#bg is restored while paused",
        /body\.paused-glow #bg\s*\{\s*visibility:\s*visible/.test(src));

  // Switching cadence introduced a visible flicker: on resume the
  // threshold drops to 500 ms instantly, but the in-flight 2 s timer
  // leaves the timestamp ~2 s old, so the next 250 ms check reads it as
  // stale and re-pauses until the delayed frame lands. Users saw the
  // wallpaper pause/resume a few times before settling. The grace window
  // suppresses the check until the probe has ticked at the new rate.
  check("a grace window exists", /_rafProbeGraceUntil/.test(src));
  check("the staleness check honours the grace window",
        /performance\.now\(\)\s*<\s*_rafProbeGraceUntil[\s\S]{0,60}?return/.test(src));
  check("grace covers a full slow beat",
        /_rafProbeGraceUntil\s*=\s*now\s*\+\s*RAF_PROBE_MS_PAUSED/.test(src));
  check("_recomputePaused notifies the probe",
        /isPaused\s*=\s*next;[\s\S]{0,600}?_rafProbeOnPauseChange\(\)/.test(src));
}

console.log("\nWallpaper Engine's own pause is detected");
{
  // WE's tray-menu pause wraps rAF, setInterval and setTimeout and queues
  // their callbacks (confirmed by inspecting webwallpaper64.exe). That
  // silences every loop the page owns — including the rAF-staleness probe
  // that was supposed to detect a host pause. Reported symptom: effects
  // and widgets froze (WE doing that), but the glow grid kept repainting
  // and no PAUSED badge appeared, because our isPaused never flipped.
  //
  // WebSocket events are not queued, so the detection has to live there.
  check("WE and Lively pauses have separate slots",
        /let _wePaused\s*=\s*false/.test(src) && /let _livelyPaused\s*=\s*false/.test(src));
  check("both feed into the combined pause state",
        /_externalPaused\s*\|\|\s*_renderingPaused\s*\|\|\s*_wePaused\s*\|\|\s*_livelyPaused/.test(src));
  // Sharing one flag was fatal: the WE detector runs on every WS message
  // and would have cleared a Lively pause the moment it saw no
  // ___wpxAnimLocked, un-pausing the wallpaper a frame after the user
  // paused it.
  check("the WE detector only writes its own slot",
        /if\s*\(paused\s*===\s*_wePaused\)\s*return;\s*_wePaused\s*=\s*paused;/.test(src));
  check("the Lively callback only writes its own slot",
        /_livelyPaused\s*=\s*paused;/.test(src));
  check("detector exists", /function _syncHostPause\(\)/.test(src));

  // Both of WE's marks are undocumented, so either one counts.
  check("reads WE's private lock flag", /___wpxAnimLocked\s*===\s*true/.test(src));
  check("also accepts the injected CSS class",
        /wpxPausePseudoAnimationAll/.test(src));
  check("probing is failure-tolerant on other hosts",
        /function _syncHostPause\(\)[\s\S]{0,700}?catch\s*\(_\)\s*\{\s*return;/.test(src));

  // Must run from the WS handler — that is the only path still executing
  // while the host has the page paused. Checking it inside renderFrame
  // alone would miss screens with no live plugin feed.
  check("called from ws.onmessage, not just renderFrame",
        /ws\.onmessage\s*=\s*\(ev\)\s*=>\s*\{[\s\S]{0,700}?_syncHostPause\(\)/.test(src));

  // Only flips on a real transition, so it does not spam _recomputePaused
  // on every inbound frame.
  check("only recomputes on an actual change",
        /if\s*\(paused\s*===\s*_wePaused\)\s*return;/.test(src));

  // The PAUSED badge is only worth setting when the page still paints.
  // Under a host pause the compositor is stopped, so the badge would
  // never appear — but it WOULD still be in the DOM when the host
  // resumed, flashing over a running wallpaper until our code cleared
  // it. Users saw exactly that: the badge showed up on resume, not on
  // pause, and lingered until they clicked.
  check("badge is suppressed for host-side pauses",
        /_badgeWorthShowing\s*=\s*isPaused\s*&&\s*_externalPaused\s*&&[\s\S]{0,120}?!_wePaused\s*&&\s*!_livelyPaused\s*&&\s*!_renderingPaused/.test(src));
  check("badge element keys off that flag",
        /classList\.toggle\("on",\s*_badgeWorthShowing\)/.test(src));
}

console.log("\neffects and widgets cover the whole desktop");
{
  // The waves preset derived its drawing width from
  // ctx.canvas.width / devicePixelRatio. But the ambient canvas is
  // scaled by _qualityScale() * _qualityDpr() -- 0.5 in Performance,
  // 0.75 in Balanced -- and devicePixelRatio is 1 in both. It therefore
  // got the BACKING width back and drew across only half or three
  // quarters of the screen, stopping dead mid-monitor. On a 5120 px
  // desktop in Balanced the waves reached 3840 px.
  check("waves reads the real transform scale",
        /getTransform\(\)/.test(src));
  check("waves no longer divides by devicePixelRatio",
        !/ctx\.canvas\.width\s*\/\s*\(window\.devicePixelRatio/.test(src));
  check("there is a fallback for hosts without getTransform",
        /_qualityScale\(\)\s*\*\s*_qualityDpr\(\)/.test(src));

  // Widgets that load remote data do it from tick(), which only runs on
  // the shared 1 Hz setInterval -- one of the things Wallpaper Engine
  // queues while paused. A widget created during a pause sat at
  // "loading" indefinitely; the weather widget only appeared after the
  // user re-saved it. A first tick is now scheduled on creation.
  check("new widgets get a first tick", /_pendingFirstTick/.test(src));
  check("the queue is drained", /function _drainFirstTicks\(\)/.test(src));
  // Must be a microtask: setTimeout and rAF are both queued by WE while
  // paused, which is the situation being worked around.
  check("drained via a microtask, not a timer",
        /Promise\.resolve\(\)\.then\(_drainFirstTicks\)/.test(src));
  check("skips widgets removed before the tick ran",
        /_drainFirstTicks[\s\S]{0,400}?isConnected/.test(src));

  // aurora and plasma draw large, very faint gradients whose radii were
  // authored as absolute pixels against 1920x1080. On a wider desktop
  // each blob covers a far smaller share of the screen and the count
  // never grew with the area. Measured on 5120x1440: mean alpha 1.5/255
  // for aurora and 3/255 for plasma -- drawn, but invisible. Users
  // reported both as "no different from off".
  check("blob radii scale with the viewport", /_ambientRadiusScale/.test(src));
  check("blob counts scale with the viewport", /_ambientCountScale/.test(src));
  for (const preset of ["aurora", "plasma"]) {
    const block = src.slice(src.indexOf(`  ${preset}: {`),
                            src.indexOf(`  ${preset}: {`) + 900);
    check(`${preset} scales its radius`,
          /_ambientRadiusScale\(w, h\)/.test(block));
    check(`${preset} scales its count`,
          /_ambientCountScale\(w, h\)/.test(block));
  }
  // Run the helpers to confirm they never shrink the authored look and
  // stay bounded on very large surfaces.
  // Brace-counted rather than a fixed character window: a budget
  // silently truncates the moment someone adds a comment, and then this
  // fails for the wrong reason — exactly what happened when
  // _ambientRadiusScale gained its quality-scaling note.
  const grab = (name) => {
    const at = src.indexOf(`function ${name}(`);
    if (at === -1) return null;
    let i = src.indexOf("{", at), depth = 0;
    for (; i < src.length; i++) {
      if (src[i] === "{") depth++;
      else if (src[i] === "}" && --depth === 0) return src.slice(at, i + 1);
    }
    return null;
  };
  const rsM = grab("_ambientRadiusScale");
  const csM = grab("_ambientCountScale");
  const hsM = grab("_qualityHaloScale");
  // The helpers close over _AMBIENT_REF_AREA, so pull that out too rather
  // than hard-coding the reference resolution here — a copy would drift.
  const refM = src.match(/const _AMBIENT_REF_AREA\s*=\s*[^;]+;/);
  check("both helpers found", !!rsM && !!csM && !!refM && !!hsM);
  if (rsM && csM && refM && hsM) {
    // Pinned to "quality" so these assertions describe the authored
    // look; the quality trade-off is covered in the parity suite.
    // eslint-disable-next-line no-new-func
    const fns = new Function(
      `const _effectQuality = "quality";\n${hsM}\n${refM[0]}\n${rsM}\n${csM}\nreturn {r:_ambientRadiusScale,c:_ambientCountScale};`)();
    check("1920x1080 is unchanged (radius)", fns.r(1920, 1080) === 1,
          String(fns.r(1920, 1080)));
    check("1920x1080 is unchanged (count)", fns.c(1920, 1080) === 1,
          String(fns.c(1920, 1080)));
    check("smaller screens are not shrunk", fns.r(1280, 720) === 1 && fns.c(1280, 720) === 1);
    check("5120x1440 grows the radius", fns.r(5120, 1440) > 1.5,
          fns.r(5120, 1440).toFixed(2));
    check("5120x1440 grows the count", fns.c(5120, 1440) > 3,
          fns.c(5120, 1440).toFixed(2));
    check("scaling is capped on huge surfaces",
          fns.r(7680, 4320) <= 3 && fns.c(7680, 4320) <= 4,
          `${fns.r(7680, 4320).toFixed(2)} / ${fns.c(7680, 4320).toFixed(2)}`);
    check("degenerate input is safe", fns.r(0, 0) === 1 && fns.c(0, 0) === 1);
  }
}

console.log("\nthe grid renderer has exactly two modes");
{
  // v2.4.6 added "canvas-prescale" — bigger backing buffer, smaller CSS
  // blur — on a -23 % Canvas 2D benchmark. On the real page it changed
  // nothing (median 5.3 % vs 4.5 %, inside the run-to-run spread): the
  // shipped blur is a CSS filter on a composited layer, and Chromium
  // already downsamples wide radii internally. v2.4.7 removed it.
  //
  // The deeper reason it could not have helped: switching the entire
  // glow grid off on a 5120x1440 span moved GPU from 2.24 % to 2.42 %.
  // The grid blur was never costing anything to save.
  //
  // These checks exist so the idea is not quietly reintroduced without
  // someone first measuring the composited path — which cannot be done
  // headless, and is why the benchmark misled in the first place.
  check("no pre-scale buffer planner remains",
        !/_gridBufferPlan|_GRID_PRESCALE/.test(src));
  // Code only — a comment recording why the mode was removed is fine
  // and worth keeping; a live string comparison against it is not.
  const codeOnly = src.replace(/\/\/[^\n]*/g, "");
  check("the renderer setting accepts only canvas or dom",
        !/canvas-prescale/.test(codeOnly));
  check("the canvas path writes the grid straight to the canvas",
        /barsCanvasCtx\.putImageData\(_gridImage, 0, 0\)/.test(src) &&
        !/_blitGridImage/.test(src));

  const cfg = readFileSync(join(repo, "wallpaper_bridge", "configurator.html"), "utf8");
  const opts = [...cfg.matchAll(/<option value="([a-z-]+)"[^>]*data-i18n="glow\.grid_renderer/g)]
    .map((m) => m[1]);
  check("the picker offers exactly canvas and dom",
        opts.length === 2 && opts.includes("canvas") && opts.includes("dom"),
        `[${opts.join(", ")}]`);
  // A config written by beta.6 still says "canvas-prescale"; it must
  // land on canvas, not silently drop the user onto the DOM path they
  // already rejected for stuttering.
  check("a stored canvas-prescale value falls back to canvas",
        /gridRenderer === "dom" \? "dom" : "canvas"/.test(cfg));
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
process.exit(results.failed.length ? 1 : 0);
