// Standby-card state machine — regression cover for issue #2.
//
// The bug: connect() built a new WebSocket without detaching the old
// one's handlers. When a superseded socket's onclose fired *after* the
// replacement had opened, it armed the standby card over a healthy
// connection — and because armStandbyCard() early-returns while a timer
// is pending and disarmStandbyCard() only ran from onopen, nothing could
// ever clear it. The card latched on permanently while frames kept
// arriving and the canvas kept rendering.
//
// This models the reconnect churn Wallpaper Engine produces on resume
// (it re-delivers the screenIndex property, so setScreenIndex() closes
// the socket to switch routes).
//
// Run: node tests/test_standby_card.mjs

// v2.4.11 checks below read the shipped page directly: the model here
// would keep passing even if index.html lost the rule it models.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class FakeWS {
  constructor() {
    this.readyState = 0;              // CONNECTING
    this.onopen = this.onclose = this.onerror = this.onmessage = null;
  }
  open() { this.readyState = 1; this.onopen?.(); }
  close() {
    const was = this.readyState;
    this.readyState = 3;
    if (was <= 1) this.onclose?.();
  }
  // Socket died earlier (host tore it down); the event lands now.
  fireLateClose() { this.readyState = 3; this.onclose?.(); }
  deliver(data) { this.onmessage?.({ data }); }
}

/**
 * Mirrors index.html's connect()/standby logic.
 * `fixed: false` reproduces the pre-2.4.2 behaviour.
 */
function makeClient({ fixed, standbyDelay = 40, reconcileMs = 15 }) {
  const st = { cardOn: false, timer: null, ws: null, connects: 0 };

  const show = (v) => { st.cardOn = v; };
  const arm = () => {
    if (st.timer) return;                       // the latch, pre-fix
    st.timer = setTimeout(() => { st.timer = null; show(true); }, standbyDelay);
  };
  const disarm = () => {
    if (st.timer) { clearTimeout(st.timer); st.timer = null; }
    show(false);
  };

  function connect() {
    st.connects++;
    if (fixed && st.ws) {
      const old = st.ws;
      old.onopen = old.onclose = old.onerror = old.onmessage = null;
      if (old.readyState <= 1) old.close();
    }
    arm();
    const sock = new FakeWS();
    st.ws = sock;
    sock.onopen = () => { if (fixed && sock !== st.ws) return; disarm(); };
    sock.onclose = () => { if (fixed && sock !== st.ws) return; arm(); };
    sock.onmessage = () => {
      if (fixed && sock !== st.ws) return;
      if (fixed && (st.timer || st.cardOn)) disarm();
    };
    return sock;
  }

  let reconciler = null;
  if (fixed) {
    reconciler = setInterval(() => {
      const live = st.ws && st.ws.readyState === 1;
      if (live && (st.cardOn || st.timer)) disarm();
      else if (!live && !st.cardOn && !st.timer) arm();
    }, reconcileMs);
  }

  return { st, connect, stop: () => reconciler && clearInterval(reconciler) };
}

// ── scenarios ────────────────────────────────────────────────────────────

/** The exact issue-#2 sequence. */
async function lateCloseScenario(fixed) {
  const c = makeClient({ fixed });
  const s1 = c.connect();
  s1.open();
  await sleep(60);

  s1.readyState = 3;          // WE tears the socket down silently
  const s2 = c.connect();     // reconnect timer fires
  s2.open();
  await sleep(60);

  s1.fireLateClose();         // the stale handler finally runs
  await sleep(120);           // well past standbyDelay

  const out = { cardOn: c.st.cardOn, live: c.st.ws.readyState === 1 };
  c.stop();
  return out;
}

async function main() {
  console.log("\nissue #2 — late close from a superseded socket");
  const before = await lateCloseScenario(false);
  const after = await lateCloseScenario(true);
  check("bug reproduces against the old logic",
        before.cardOn === true && before.live === true,
        `got ${JSON.stringify(before)}`);
  check("fixed logic keeps the card down over a live socket",
        after.cardOn === false && after.live === true,
        `got ${JSON.stringify(after)}`);

  console.log("\ngenuine disconnect still surfaces");
  {
    const c = makeClient({ fixed: true });
    const s = c.connect();
    s.open();
    await sleep(50);
    s.close();                       // real drop, nothing reconnects
    await sleep(120);
    check("card appears when the socket is really gone", c.st.cardOn === true);
    c.stop();
  }

  console.log("\nreconnect clears the card again");
  {
    const c = makeClient({ fixed: true });
    const s1 = c.connect();
    s1.open();
    await sleep(50);
    s1.close();
    await sleep(120);
    check("card is up after the drop", c.st.cardOn === true);
    const s2 = c.connect();
    s2.open();
    await sleep(60);
    check("card clears once reconnected", c.st.cardOn === false);
    c.stop();
  }

  console.log("\nreconciler self-heals a swallowed onopen");
  {
    // Host delivers no onopen at all (bfcache-style restore): the
    // edge-driven logic would stay latched; the reconciler must not.
    const c = makeClient({ fixed: true });
    const sock = c.connect();
    await sleep(80);
    check("card is up while genuinely not connected", c.st.cardOn === true);
    sock.readyState = 1;             // silently becomes live, no event
    await sleep(80);
    check("reconciler clears the card without an onopen", c.st.cardOn === false);
    c.stop();
  }

  console.log("\ninbound traffic clears a stale card");
  {
    const c = makeClient({ fixed: true, reconcileMs: 100000 }); // reconciler off
    const sock = c.connect();
    await sleep(80);
    check("card latched before traffic arrives", c.st.cardOn === true);
    sock.readyState = 1;
    sock.deliver(new ArrayBuffer(8));
    await sleep(20);
    check("a received frame clears the card", c.st.cardOn === false);
    c.stop();
  }

  console.log("\nrepeated reconnect churn leaves no stale handlers");
  {
    const c = makeClient({ fixed: true });
    const sockets = [];
    for (let i = 0; i < 5; i++) {
      const s = c.connect();
      s.open();
      sockets.push(s);
      await sleep(20);
      s.readyState = 3;
    }
    const live = c.connect();
    live.open();
    await sleep(60);
    // Every superseded socket fires late, all at once.
    sockets.forEach((s) => s.fireLateClose());
    await sleep(120);
    check("card stays down after 5 stale closes",
          c.st.cardOn === false && c.st.ws.readyState === 1,
          `cardOn=${c.st.cardOn}`);
    c.stop();
  }

  // ── v2.4.11: the second reason the card exists ─────────────────
  //
  // Until now the card meant exactly one thing: the bridge process is
  // unreachable. The far more common first-run failure is the inverse
  // — bridge reachable, socket live, and SignalRGB never got the
  // device dragged onto its canvas. No frames arrive, the screen is
  // black, and the card stayed hidden PRECISELY BECAUSE the bridge was
  // fine. Total silence at the one moment a new user needs a sentence.
  //
  // Checked against the shipped source rather than the model: the
  // model would happily keep passing if the real page lost the rule.
  {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..",
           "wallpaper_bridge", "wallpaper", "index.html"), "utf8");

    check("a starvation grace period is defined",
          /const NOFRAME_GRACE_MS = (\d+)/.test(src));
    const grace = Number((src.match(/const NOFRAME_GRACE_MS = (\d+)/) || [])[1] || 0);
    // Long enough to ride out an effect switch or a resume, short
    // enough that a stuck setup is explained while the user is still
    // looking at it.
    check("grace is between 5s and 60s", grace >= 5000 && grace <= 60000, String(grace));

    check("the reconciler tests for starvation",
          /const starved = live && !isPaused/.test(src));
    // A paused wallpaper legitimately receives nothing. Blaming
    // SignalRGB for that would send the user to the wrong app.
    check("a paused wallpaper is never called starved",
          /starved = live && !isPaused/.test(src));
    check("starvation raises the card with its own reason",
          /showStandbyCard\(true, "noframes"\)/.test(src));

    // The timestamp has to be taken before both the pause check and
    // the frame-rate gate: it answers "is the sender sending", not
    // "did we choose to draw".
    // Scoped to renderFrame's body: there are three `if (isPaused)
    // return;` statements in the file, so searching forward from the
    // stamp just finds a later unrelated one and passes regardless.
    // The first version of this check did exactly that and survived a
    // mutation that moved the stamp below the pause check.
    const rfAt = src.indexOf("function renderFrame(buf) {");
    const rfEnd = src.indexOf("\nfunction ", rfAt + 10);
    const rf = src.slice(rfAt, rfEnd === -1 ? rfAt + 4000 : rfEnd);
    const stampAt = rf.indexOf("_lastFrameAtMs = Date.now()");
    const pauseAt = rf.indexOf("if (isPaused) return;");
    check("frame arrival is stamped before the pause check",
          stampAt !== -1 && pauseAt !== -1 && stampAt < pauseAt,
          `stamp@${stampAt} pause@${pauseAt}`);
    // Same reasoning for the frame-rate gate: a 20 Hz cap must not read
    // as starvation at 30 Hz.
    const gateAt = rf.indexOf("RENDER_INTERVAL_MS) return;");
    check("frame arrival is stamped before the frame-rate gate",
          gateAt === -1 || stampAt < gateAt, `stamp@${stampAt} gate@${gateAt}`);
    // let is not hoisted; v2.4.4-beta.7 shipped exactly this mistake
    // with gridRenderer and the page died on load.
    check("the timestamp is declared before it is assigned",
          src.indexOf("let _lastFrameAtMs") < src.indexOf("_lastFrameAtMs = Date.now()"));

    // The card was the last hardcoded-English surface in an otherwise
    // bilingual product — and it appears exactly when a confused user
    // is reading it.
    check("card text exists in both languages",
          /STANDBY_TEXT/.test(src) && /noframes:/.test(src) &&
          /de: \[/.test(src));
    check("language comes from the bridge push",
          /window._wallpaperLang = msg.language/.test(src));
  }

  const total = results.passed + results.failed.length;
  console.log(`\n  ${results.passed}/${total} passed`);
  process.exit(results.failed.length ? 1 : 0);
}

main();
