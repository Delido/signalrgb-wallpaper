// Ambilight mode — the wallpaper as a light source rather than a picture.
//
// WHY THIS EXISTS
//
// A user described running his side monitors as ambilights while
// watching something on the main screen, and mentioned in passing that
// he had made "a 1x1 transparent png for the wallpaper" to get there.
// That is a workaround for a missing setting, and a fragile one: it
// depends on a transparent PNG surviving upload, format sniffing and
// rendering untouched, none of which is tested for transparency.
//
// Two separate things fight an ambilight, and BOTH have to go or the
// feature does nothing:
//
//   1. `html, body` paint a radial gradient (#0a0a14 -> #000). It is
//      lighter than black in the middle, so a dim glow reads as washed
//      out grey instead of colour on black.
//   2. `#bg` sits at z-index 2 and the glow at z-index 1 — the image
//      layer is ON TOP of the glow and dilutes it.
//
// The risk with a setting like this is not that it fails loudly. It is
// that it gets filtered out somewhere along the chain (default ->
// whitelist -> push -> page) and silently does nothing, which has
// happened before in this project: pill height and width were settable
// on the bridge for many versions while the Configurator had no
// control, and `language` had a config field, validation and both
// translation tables while nothing could write it.
//
// So these checks walk the whole chain rather than testing one end.
//
// Run: node tests/test_ambient_mode.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "wallpaper_bridge", "wallpaper", "index.html"), "utf8");
const conf = readFileSync(join(ROOT, "wallpaper_bridge", "configurator.html"), "utf8");
const bridge = readFileSync(join(ROOT, "wallpaper_bridge", "bridge.py"), "utf8");

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

console.log("\nambilight mode — the setting reaches the page");

// ── the bridge half of the chain ──────────────────────────────────────
check("the setting has a default",
      /"ambientMode":\s*False/.test(bridge),
      "without a default the key never exists on a fresh config");
check("it defaults to off",
      /"ambientMode":\s*False/.test(bridge),
      "every existing install must look exactly as it did");
// The whitelist is the step that silently drops settings. A key absent
// here is accepted by the Configurator, sent, and discarded server-side
// with nothing visible to the user.
const wl = bridge.slice(bridge.indexOf("_SETTABLE_SCREEN_KEYS = {"),
                        bridge.indexOf("_SETTABLE_SCREEN_KEYS = {") + 2500);
check("it is on the settable whitelist", /"ambientMode"/.test(wl),
      "otherwise setting-update accepts it and throws it away");
// Presets capture the visual identity of a screen. An ambilight screen
// whose preset does not carry this restores as a normal wallpaper.
const ps = bridge.slice(bridge.indexOf("PRESET_SNAPSHOT_KEYS = ("),
                        bridge.indexOf("PRESET_SNAPSHOT_KEYS = (") + 1800);
check("presets carry it", /"ambientMode"/.test(ps));
// ...but it must NOT be treated as a hardware-perf knob, or a Quick
// Look could never turn it on — which is exactly what the Ambilight
// bundle needs to do.
const fb = bridge.slice(bridge.indexOf("_BUNDLE_FORBIDDEN_KEYS = frozenset({"),
                        bridge.indexOf("_BUNDLE_FORBIDDEN_KEYS = frozenset({") + 400);
check("quick looks are allowed to set it", !/ambientMode/.test(fb),
      "it is a visual choice, not a hardware preference");

// ── the page half ─────────────────────────────────────────────────────
check("the page handles the setting",
      /case "ambientMode":/.test(page));
// Both elements carry the gradient. body covers html at 100% height
// today, but that is incidental — a zoom or fractional DPR can leave a
// hairline of html showing, and a grey seam on a black ambilight only
// ever shows up on someone else's monitor.
check("the class goes on body", /classList\.toggle\("ambient-mode"/.test(page));
check("the class goes on html too",
      /documentElement\.classList\.toggle\("ambient-mode"/.test(page),
      "html carries the same gradient as body");

// The two obstacles, asserted separately: killing one without the other
// leaves the mode looking broken in a different way each time.
check("ambient mode overrides the gradient",
      /html\.ambient-mode,\s*body\.ambient-mode\s*\{\s*background:\s*#000/.test(page),
      "the radial gradient is lighter than black and greys out the glow");
check("ambient mode hides the image layer",
      /body\.ambient-mode\s*#bg\s*\{\s*display:\s*none/.test(page),
      "#bg is at z-index 2, ON TOP of the glow at z-index 1");

// The premise of the second rule. If #bg ever moves behind #bars this
// test should fail loudly rather than keep asserting a stale reason.
const bgZ = /#bg\s*\{[^}]*z-index:\s*(\d+)/.exec(page);
const barsZ = /#bars\s*\{[^}]*z-index:\s*(\d+)/.exec(page);
check("the image really does paint above the glow",
      bgZ && barsZ && Number(bgZ[1]) > Number(barsZ[1]),
      `bg=${bgZ && bgZ[1]} bars=${barsZ && barsZ[1]} — if this flips, hiding #bg is no longer the fix`);

// ── the Configurator half ─────────────────────────────────────────────
check("there is a control for it", /id="ambient-mode"/.test(conf),
      "a bridge setting with no UI is how pill height stayed hidden");
check("the control writes the setting",
      /setSetting\("ambientMode", els\.ambientMode\.checked\)/.test(conf));
check("the control reflects the saved value",
      /els\.ambientMode\.checked = !!settings\.ambientMode/.test(conf),
      "otherwise it resets visually on every reload");
check("it is translated", /"bg\.ambient_mode":/.test(conf) &&
                          /"bg\.ambient_mode_hint":/.test(conf));
check("the German string is real, not the English one",
      /"bg\.ambient_mode":\s*\{\s*en:\s*"Ambilight mode",\s*de:\s*"Ambilight-Modus"/.test(conf));

// Dimming the overridden controls: styled by container, not by a list
// of ids, so a row added to the card later is covered automatically.
check("the overridden controls are dimmed",
      /#card-bg\.ambient-on \.body > \*:not\(#ambient-mode-row\)/.test(conf),
      "a hard-coded id list would silently miss rows added later");
check("the ambilight row itself stays usable",
      /:not\(#ambient-mode-row\)/.test(conf),
      "dimming it would leave no way to switch the mode back off");
check("the row carries that id", /id="ambient-mode-row"/.test(conf));

// -- v2.5.2-beta.3: it has to look like the mode switch it is --------
// "ambilight muss hier auch viel schoener designt werden, das echt nur
// dahin geklatscht". It was a bare checkbox in a column of checkboxes,
// which misrepresented a control that disables the rest of the card.
console.log("\nthe control reads as a mode switch");

check("it is its own block, not a settings row",
      /<div class="mode-toggle" id="ambient-mode-row">/.test(conf),
      "a peer of the rows it disables understates what it does");
check("the whole block is the label",
      /<label class="mode-toggle-main" for="ambient-mode">/.test(conf),
      "clicking the description should toggle it too");
// Scoped to the block's MARKUP. A class name still present in the
// stylesheet says nothing about whether the element exists -- three
// mutations that stripped elements from the HTML passed a whole-file
// check on the class name alone.
const mt = conf.slice(conf.indexOf('<div class="mode-toggle" id="ambient-mode-row">'),
                      conf.indexOf('<!-- v2.2.0-beta: prominent current-background'));
check("the block markup was located", mt.length > 300 && mt.length < 4000,
      `${mt.length} chars -- anchor moved, the checks below are blind`);
check("title and description are separate elements in the markup",
      /class="mode-toggle-title"/.test(mt) && /class="mode-toggle-desc"/.test(mt),
      "one run-on line was the original complaint");
check("there is an icon in the markup",
      /class="mode-toggle-icon"/.test(mt) && /<svg/.test(mt));
check("the active state is visible on the block",
      /#card-bg\.ambient-on \.mode-toggle\s*\{/.test(conf),
      "the switch alone is a small target for 'is this on?'");

// The native checkbox has to survive: every binding, the i18n pass and
// the checks above address it by id. display:none would take it out of
// the tab order and off screen readers, so it is moved out of view
// with opacity instead.
check("the native checkbox is still in the DOM",
      /<input type="checkbox" id="ambient-mode"/.test(conf));
const mtCss = conf.slice(conf.indexOf(".mode-toggle-input {"),
                         conf.indexOf(".mode-toggle-switch {"));
check("it is hidden without leaving the tab order",
      /opacity:\s*0/.test(mtCss) && !/display:\s*none/.test(mtCss),
      "display:none would make the control unreachable by keyboard");
check("keyboard focus stays visible",
      /\.mode-toggle-input:focus-visible ~ \.mode-toggle-switch/.test(conf),
      "an invisible checkbox with no focus ring is unusable by keyboard");
// Both halves of the checked state: the track AND the knob. Dropping
// only the track rule left the switch visually dead while the knob
// still moved, and a single check passed it.
check("the switch track reflects the checked state",
      /\.mode-toggle-input:checked ~ \.mode-toggle-switch \{/.test(conf),
      "the visible control must follow the real one");
check("the switch knob moves when checked",
      /\.mode-toggle-input:checked ~ \.mode-toggle-switch::after/.test(conf),
      "a track that changes colour without the knob moving reads as broken");

console.log("\nthe Ambilight quick look");

const bundleAt = conf.indexOf('id: "ambilight"');
const bundleEnd = conf.indexOf("\n  {", bundleAt);
const bundle = conf.slice(bundleAt, bundleEnd === -1 ? bundleAt + 2000 : bundleEnd);

check("the bundle exists", bundleAt !== -1);
check("it turns the mode on", /ambientMode:\s*true/.test(bundle));
check("it shows the glow", /showBars:\s*true/.test(bundle) &&
                            /barLayout:\s*"lay-grid"/.test(bundle),
      "lay-off hides the bars entirely — nothing would light up");

// The blur is the whole point: at a typical 32x32 canvas the zones are
// large, and too little blur leaves visible cell edges on a wide panel.
const blur = /gridBlur:\s*(\d+)/.exec(bundle);
check("it sets a heavy blur", blur && Number(blur[1]) > 120,
      `${blur && blur[1]} — must exceed the old 120 ceiling to be worth the feature`);

// Anything drawn on top of the panel is a dark patch in the light.
for (const off of ["ambientEffect", "audioGlow", "pixelfx"]) {
  check(`${off} is off in the bundle`,
        new RegExp(off + ':\\s*"off"').test(bundle),
        "overlays read as dark shapes in flat light");
}
check("no widgets", /widgets:\s*\[\s*\]/.test(bundle),
      "a widget is a dark rectangle in the middle of a light source");
check("the look is translated", /"looks\.ambilight\.name":/.test(conf) &&
                                 /"looks\.ambilight\.desc":/.test(conf));

// The ceiling itself. Raising it is what makes the blur above reachable
// from the slider at all; without it the bundle sets a value the user
// can never restore after touching the control.
const sliderMax = /id="grid-blur"[^>]*max="(\d+)"/.exec(conf);
check("the blur slider reaches the bundle's value",
      sliderMax && blur && Number(sliderMax[1]) >= Number(blur[1]),
      `slider max=${sliderMax && sliderMax[1]} bundle=${blur && blur[1]} — ` +
      "a preset value the slider cannot reach is a one-way door");

// The first-run wizard deliberately does NOT offer this: someone
// setting the product up for the first time does not want a screen
// that only glows.
check("the wizard does not offer ambilight",
      !/WIZ_LOOK_IDS = \[[^\]]*ambilight/.test(conf),
      "a first-time user would read a black glowing screen as broken");

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
process.exit(results.failed.length ? 1 : 0);
