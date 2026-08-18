// The Configurator's setup-status banner.
//
// WHY THIS EXISTS
//
// Getting a working wallpaper takes six steps. Two of them are neither
// automated nor were they detected until v2.4.11:
//
//   * dragging the "Desktop Wallpaper" device onto the SignalRGB canvas
//   * assigning the wallpaper to a monitor in Lively / Wallpaper Engine
//
// Miss the first and everything *looks* fine: the bridge is up, the
// Configurator's pill says "connected", the wallpaper page holds a live
// socket. No frames arrive, so the screen is black — and the wallpaper's
// own "bridge offline" card stays hidden precisely because the bridge is
// NOT offline. A new user gets a black screen and no explanation
// anywhere in the product.
//
// The bridge has known all of this since v0.8.9 (get_health_status), but
// it was only ever rendered in a tray dialog a first-time user has no
// reason to open.
//
// These tests run the real decision table out of configurator.html
// rather than re-describing it here — a second copy of the rules would
// drift from the first, which is the exact failure the preset-parity
// suite was written for.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..");
const CFG = readFileSync(join(repo, "wallpaper_bridge", "configurator.html"), "utf8");

const results = { passed: 0, failed: [] };
function check(label, cond, detail = "") {
  if (cond) { results.passed++; console.log(`  PASS  ${label}`); }
  else { results.failed.push(label); console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`); }
}

console.log("\nthe decision table is present and loadable");
const m = CFG.match(/const SETUP_STEPS = \[[\s\S]*?\n\];/);
check("SETUP_STEPS found in configurator.html", !!m);
if (!m) {
  console.log(`\n  ${results.passed}/${results.passed + results.failed.length} passed`);
  process.exit(1);
}
// eslint-disable-next-line no-new-func
const STEPS = new Function("t", `${m[0]}; return SETUP_STEPS;`)((k) => k);

const ids = STEPS.map((s) => s.id);
check("covers all four signals", ids.length === 4, ids.join(","));
// Order is load-bearing: only the first failing step is shown, and a
// later step usually fails *because* an earlier one did. Listing
// "SignalRGB isn't sending" above "SignalRGB isn't running" would send
// the user to the wrong app.
check("ordered from root cause outwards",
      ids.join(",") === "plugin,signalrgb,frames,assigned", ids.join(","));

/** Which step would the banner name for this health snapshot? */
function firstProblem(h) {
  const failed = STEPS.filter((s) => !s.ok(h));
  return failed.length ? failed[0].id : null;
}

const HEALTHY = {
  plugin_present: true, signalrgb_running: true,
  frames_arriving: true, pages_per_screen: [1, 1],
};

console.log("\nit stays silent when the chain works");
{
  check("a healthy install reports no problem", firstProblem(HEALTHY) === null);
  // Single screen, single page — the common case must not read as
  // "screen 2 is missing a wallpaper".
  check("a single-screen install is healthy too",
        firstProblem({ ...HEALTHY, pages_per_screen: [1] }) === null);
}

console.log("\nit names the right step for each break");
{
  check("missing plugin file",
        firstProblem({ ...HEALTHY, plugin_present: false }) === "plugin");
  check("SignalRGB not running",
        firstProblem({ ...HEALTHY, signalrgb_running: false,
                       frames_arriving: false }) === "signalrgb");
  // The silent black screen: everything installed and running, device
  // never placed on the canvas. This is the case that had no feedback
  // anywhere in the product before v2.4.11.
  check("device never placed on the SignalRGB canvas",
        firstProblem({ ...HEALTHY, frames_arriving: false }) === "frames");
  check("one screen has no wallpaper assigned",
        firstProblem({ ...HEALTHY, pages_per_screen: [1, 0] }) === "assigned");
}

console.log("\nit blames the cause, not the symptom");
{
  // With SignalRGB closed, frames also stop. The banner must send the
  // user to "start SignalRGB", not to "drag the device onto the canvas"
  // — the second instruction is useless while the app is shut.
  check("a closed SignalRGB is reported as such, not as missing frames",
        firstProblem({ ...HEALTHY, signalrgb_running: false,
                       frames_arriving: false }) === "signalrgb");
  // Same shape one step earlier.
  check("a missing plugin outranks everything downstream",
        firstProblem({ plugin_present: false, signalrgb_running: false,
                       frames_arriving: false, pages_per_screen: [0, 0] }) === "plugin");
}

console.log("\nit survives a health payload it doesn't recognise");
{
  // /health is fetched over HTTP and could answer with an older or
  // partial shape. Throwing here would take the whole Configurator
  // script down with it.
  let threw = false;
  try { firstProblem({}); } catch (_) { threw = true; }
  check("an empty payload does not throw", !threw);
  // pages_connected is the pre-v2.4.11 field; the fallback keeps an
  // older bridge from reading as "no wallpaper anywhere".
  check("falls back to the old pages_connected total",
        firstProblem({ plugin_present: true, signalrgb_running: true,
                       frames_arriving: true, pages_connected: 2 }) === null);
}

console.log("\nthe banner is wired into the page");
{
  check("markup anchor exists", /id="setup-status"/.test(CFG));
  check("starts hidden — no green banner to train people to ignore",
        /id="setup-status"[^>]*class="hidden"/.test(CFG));
  check("polls /health", /fetch\("\/health"/.test(CFG));
  check("polling is uncached", /"\/health",\s*\{\s*cache:\s*"no-store"\s*\}/.test(CFG));
  check("renders through the i18n table, not hardcoded English",
        /t\("setup\.step\." \+ first\.id\)/.test(CFG));
  // Every step id needs a matching translation, or the banner shows a
  // raw key at exactly the moment the user is most confused.
  for (const id of ids) {
    check(`"setup.step.${id}" is translated in both languages`,
          new RegExp(`"setup\\.step\\.${id}"[\\s\\S]{0,900}?de:`).test(CFG));
  }
  check("the fix button reuses the existing system-action channel",
        /sendCmd\(\{ type: "system-action", action: "open-plugins-folder" \}\)/.test(CFG));
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
if (results.failed.length) {
  console.log("\n  failed:");
  for (const f of results.failed) console.log(`    - ${f}`);
}
process.exit(results.failed.length ? 1 : 0);
