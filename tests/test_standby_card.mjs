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

  // -- v2.5.1: a fullscreen app is not SignalRGB's fault --------------
  //
  // Reported as: "wenn ich eine Fullscreen anwendung an habe aber nicht
  // im vordergrund poppt das jede sekunde auf".
  //
  // The pause watcher only inspects GetForegroundWindow(), so a
  // fullscreen app that is NOT focused leaves the bridge unpaused --
  // isPaused stays false on the page while frames stop anyway
  // (SignalRGB backgrounded, or the host closed the page on that
  // monitor). The card then accused a perfectly configured install,
  // once every 500 ms, on a surface with no close button.
  {
    const src = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..",
           "wallpaper_bridge", "wallpaper", "index.html"), "utf8");
    const bridge = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..",
           "wallpaper_bridge", "bridge.py"), "utf8");

    // The page side. Naming the flag is not the same as consulting it:
    // assert it is part of the starvation conjunction itself, in the
    // same statement, so a mutation that declares it and forgets the
    // guard fails.
    check("the flag is declared before the reconciler reads it",
          src.indexOf("let _fullscreenAnywhere") !== -1 &&
          src.indexOf("let _fullscreenAnywhere") <
            src.indexOf("!_fullscreenAnywhere"));
    check("a fullscreen app suppresses the starvation card",
          /const starved = live && !isPaused && !_fullscreenAnywhere/.test(src),
          "the flag must gate `starved`, not merely exist");
    check("the flag is set from the bridge message",
          /msg\.type === "fullscreen"/.test(src) &&
          /_fullscreenAnywhere = !!msg\.active/.test(src));

    // The whole point of option A: this must not become a pause. If a
    // future edit routes it into setPaused/_externalPaused, a
    // fullscreen video on an unwatched monitor would freeze the
    // wallpaper on every screen, because the pause is bridge-global.
    const fsAt = src.indexOf('msg.type === "fullscreen"');
    const fsEnd = src.indexOf("} else if", fsAt + 10);
    const fsBody = src.slice(fsAt, fsEnd === -1 ? fsAt + 800 : fsEnd);
    check("the fullscreen message never pauses the page",
          !/setPaused|_externalPaused|_recomputePaused/.test(fsBody),
          "advisory only -- pausing here would stop every screen");

    // The bridge side. Same distinction, and it is the one that was
    // wrong: two questions, two functions.
    // Scoped to _poll_anywhere's own body. Asserting the name appears
    // somewhere in a 14k-line file is not an assertion: a mutation
    // that swapped this for the foreground-only check sailed past the
    // first version of this line.
    const chr10 = String.fromCharCode(10);
    const paAt = bridge.indexOf("def _poll_anywhere(self):");
    const paEnd = bridge.indexOf(chr10 + chr10 + "# ====", paAt);
    const paBody = bridge.slice(paAt, paEnd === -1 ? paAt + 900 : paEnd);
    check("the anywhere-poll exists", paAt !== -1);
    check("it asks about all monitors, not just the foreground",
          /_fullscreen_on_any_monitor\(\)/.test(paBody) &&
          !/_is_fullscreen_active\(\)/.test(paBody),
          "the foreground check is the bug this fixes");
    // Both the presence AND the position matter: an indexOf that finds
    // nothing returns -1, which compares as "earlier" and passed a
    // mutation that deleted the call outright.
    const pollAt = bridge.indexOf("self._poll_anywhere()");
    const gateAt2 = bridge.indexOf("if not self._enabled():");
    check("the anywhere-poll runs even when auto-pause is disabled",
          pollAt !== -1 && gateAt2 !== -1 && pollAt < gateAt2,
          "a user who turned pausing off still must not be misinformed");
    check("the state reaches the pages",
          /def push_fullscreen\(/.test(bridge) &&
          /"type": "fullscreen"/.test(bridge));
    check("a page connecting mid-game is told immediately",
          /initial fullscreen push failed/.test(bridge),
          "otherwise it shows the wrong card until the next flip");

    // The pause path must keep keying off the foreground window.
    const onFsAt = bridge.indexOf("def _on_fullscreen_anywhere");
    const onFsEnd = bridge.indexOf(chr10 + "    @staticmethod", onFsAt);
    const onFsBody = bridge.slice(onFsAt, onFsEnd === -1 ? onFsAt + 1200 : onFsEnd);
    check("the anywhere handler does not touch the pause flag",
          onFsAt !== -1 && !/self\._paused\s*=/.test(onFsBody) &&
          !/push_pause/.test(onFsBody),
          "frames must keep flowing -- this only silences a card");
  }

  // -- v2.5.2-beta.3: the card must not flash ------------------------
  //
  // Reported as "aber das rumflashen ist unschoen", with SignalRGB's
  // devices disabled -- so the card was RIGHT, it just could not hold
  // still.
  //
  // Two handlers disagreed. ws.onmessage cleared the card on any
  // inbound message (correct in v2.4.2, when the card only ever meant
  // "bridge unreachable"); the 500 ms reconciler re-raised it while no
  // GLOW frame had arrived for 15 s. The bridge pushes sysstats once a
  // second regardless of whether SignalRGB feeds it, so the two fought
  // at 1 Hz.
  //
  // Simulated rather than grepped: the bug is an interaction between
  // two timers, and no amount of reading either one in isolation shows
  // it. This models both and counts transitions.
  {
    const NOFRAME_GRACE = 60;    // scaled down from 15 s
    const RECONCILE = 10;        // from 500 ms
    const STATS_EVERY = 20;      // the bridge's 1 Hz sysstats push

    function makeStandby({ scopedDisarm }) {
      const st = { on: false, reason: "offline", flips: 0, lastFrameAt: 0 };
      const show = (reason) => {
        if (!st.on) st.flips++;
        st.on = true; st.reason = reason;
      };
      const disarm = () => { if (st.on) st.flips++; st.on = false; };

      // ws.onmessage — every inbound message, glow frame or not.
      const onMessage = (isGlowFrame) => {
        if (st.on) {
          // The fix: a non-frame message is no evidence about frames.
          if (!scopedDisarm || st.reason !== "noframes") disarm();
        }
        if (isGlowFrame) st.lastFrameAt = Date.now();
      };

      const tick = () => {
        const starved = st.lastFrameAt > 0 &&
                        (Date.now() - st.lastFrameAt) > NOFRAME_GRACE;
        if (starved) {
          if (!st.on || st.reason !== "noframes") show("noframes");
        } else if (st.on) {
          disarm();
        }
      };
      return { st, onMessage, tick };
    }

    async function run({ scopedDisarm }) {
      const c = makeStandby({ scopedDisarm });
      c.st.lastFrameAt = Date.now();          // a frame arrived once
      const recon = setInterval(c.tick, RECONCILE);
      // SignalRGB is dead, but the bridge keeps pushing sysstats.
      const stats = setInterval(() => c.onMessage(false), STATS_EVERY);
      await sleep(NOFRAME_GRACE + 20);        // let the card come up
      const flipsBefore = c.st.flips;
      await sleep(200);                        // ~10 sysstats pushes
      clearInterval(recon); clearInterval(stats);
      return { settled: c.st.flips - flipsBefore, on: c.st.on,
               reason: c.st.reason };
    }

    const before = await run({ scopedDisarm: false });
    const after  = await run({ scopedDisarm: true });

    check("the flashing reproduces against the old logic",
          before.settled > 4,
          `only ${before.settled} transitions — the model is not `
          + "reproducing the bug, so the next check proves nothing");
    check("the card holds still once it is up",
          after.settled === 0,
          `${after.settled} transitions while SignalRGB stayed silent`);
    check("and it is still showing the right thing",
          after.on === true && after.reason === "noframes",
          "holding still must not mean giving up on the message");

    // The other direction: real frames must still clear it, or the fix
    // trades a flashing card for a stuck one.
    {
      const c = makeStandby({ scopedDisarm: true });
      c.st.lastFrameAt = Date.now();
      const recon = setInterval(c.tick, RECONCILE);
      await sleep(NOFRAME_GRACE + 30);
      const wasUp = c.st.on;
      c.onMessage(true);                       // SignalRGB comes back
      await sleep(RECONCILE * 3);
      clearInterval(recon);
      check("a real glow frame still clears the card",
            wasUp === true && c.st.on === false,
            `up=${wasUp} then on=${c.st.on}`);
    }

    // And the offline card must keep its original behaviour: any
    // message proves reachability, which is what v2.4.2 fixed.
    {
      const c = makeStandby({ scopedDisarm: true });
      c.st.on = true; c.st.reason = "offline";
      c.onMessage(false);
      check("an offline card is still cleared by any message",
            c.st.on === false,
            "narrowing the disarm must not regress issue #2");
    }

    // Finally, pin it in the shipped source.
    //
    // Scoped to ws.onmessage's body. `_standbyReason !== "noframes"`
    // appears TWICE in the file -- the reconciler has its own copy at
    // the noframes branch -- so a whole-file regex matches the OTHER
    // one and passes even with this fix fully reverted. It did exactly
    // that: two mutations walked straight through the first version of
    // this check.
    const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..",
                "wallpaper_bridge", "wallpaper", "index.html"), "utf8");
    const omAt = src.indexOf("ws.onmessage = (ev) => {");
    const omEnd = src.indexOf("ws.onerror", omAt);
    const om = omAt === -1 ? "" : src.slice(omAt, omEnd === -1 ? omAt + 6000 : omEnd);
    check("ws.onmessage was located", om.length > 200,
          `${om.length} chars — the anchor moved, this check is blind`);
    check("onmessage clears the card only when it is not about frames",
          /_standbyReason !== "noframes"/.test(om) &&
          /disarmStandbyCard\(\)/.test(om),
          "an unconditional disarm here fights the reconciler at 1 Hz");
    // And that the guard actually gates the call rather than sitting
    // in some unrelated statement in the same function.
    check("the guard is on the disarm itself",
          /_standbyReason !== "noframes"\) \{/.test(om) &&
          om.indexOf('_standbyReason !== "noframes"') <
            om.indexOf("disarmStandbyCard();"),
          "the condition and the call must be one statement");
  }

  const total = results.passed + results.failed.length;
  console.log(`\n  ${results.passed}/${total} passed`);
  process.exit(results.failed.length ? 1 : 0);
}

main();
