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

console.log("\nversion stamping");
{
  const bridgePy = readFileSync(join(repo, "wallpaper_bridge", "bridge.py"), "utf8");
  const wpVer = bridgePy.match(/^WALLPAPER_VERSION\s*=\s*"([^"]+)"/m)?.[1];
  check("bridge.py declares WALLPAPER_VERSION", !!wpVer, `got ${wpVer}`);
  check("index.html declares a WALLPAPER_VERSION constant",
        /WALLPAPER_VERSION\s*=/.test(src));
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
process.exit(results.failed.length ? 1 : 0);
