# Publishing to Steam Workshop

This is a cheatsheet for the maintainer (Sebastian) — the step-by-step for
pushing the three SignalRGB Glow wallpapers to the [Wallpaper Engine Steam
Workshop](https://steamcommunity.com/app/431960/workshop/). The bundles are
already produced by `installer/build.ps1`; the rest is a UI flow inside
Wallpaper Engine.

## Prerequisites

- A Steam account that owns Wallpaper Engine.
- The bundles built locally: run `pwsh installer/build.ps1` once and confirm
  `wallpaper_bridge/we_bundles/SignalRGB_Glow_Screen{1,2,3}/` each contain
  - `index.html`
  - `LivelyInfo.json` (Lively manifest — harmless extra in a WE folder)
  - `project.json` (the WE manifest — title, BBCode description, tags)
  - `interact.min.js` + `interact.LICENSE.txt`
  - `thumbnail.png`
  - `workshop_preview.png` (1920×1080 — the listing image Workshop browses)

The installer's *"Install for Wallpaper Engine"* task copies these into
Steam's `steamapps\common\wallpaper_engine\projects\myprojects\` for you.
You can also drop the folders there manually.

## Upload flow (per wallpaper, ~5 min)

1. Open **Wallpaper Engine** on Steam.
2. Tab **Workshop** → **Manage** → **My Wallpapers**. You should see all
   three *SignalRGB Glow - Screen N* entries.
3. Right-click the first one → **Workshop → Share**. WE opens its upload
   panel.
4. Fill in:
   - **Title:** pre-filled from `project.json` ("SignalRGB Glow - Screen 1").
     Leave as-is.
   - **Description:** pre-filled from `project.json` (BBCode, with bridge
     requirement + GitHub link prominently up top). Review once for typos.
   - **Tags:** pre-filled from `project.json` (`RGB`, `Customizable`,
     `Web`, `Abstract`, `Other`). Workshop will show its own tag picker;
     you can add more like `Multi-Monitor`.
   - **Preview image:** Workshop wants its own preview file. Click
     **Browse** and pick `workshop_preview.png` from the same folder
     (`…\myprojects\SignalRGB_Glow_Screen1\workshop_preview.png`).
   - **Visibility:** **Public** for general release. Use **Friends** or
     **Private** for a soft-launch / a friend-test.
   - **Change notes** (only on later uploads): explain what's new.
5. Accept the Steam Workshop Terms (only the very first upload of your
   life).
6. Hit **Submit**. Steam processes for ~30–60 s, then a "View in browser"
   button appears.
7. Repeat for Screen 2 and Screen 3.

Each item gets its own Workshop ID (large integer in the URL).

## After upload — quality-of-life

- **Cross-link the three items** in each description's footer ("Also
  available: Screen 2 / Screen 3"). The Workshop URLs only exist after the
  first upload, so do this as a follow-up edit on each.
- **Pin a screenshot** of the wallpaper actually running (with cutouts +
  glow) once you have one. The procedural `workshop_preview.png` is good
  for first-launch but a real screenshot is more convincing.
- Set the **License field** to *MIT* (Workshop UI dropdown) for clarity.

## Re-publishing after a bridge update

Every time the bridge is re-released (= new build of `installer/build.ps1`)
the `index.html` inside each WE bundle changes. Subscribed users get the
new HTML the next time they restart Wallpaper Engine — **only if you
republish the Workshop items**.

- Workshop pulls from the same `…\myprojects\SignalRGB_Glow_ScreenN\`
  folder you uploaded from. Make sure that folder has the freshly-built
  files (the installer task overwrites in place).
- In WE: **Workshop → Manage → My Wallpapers** → right-click your
  existing item → **Workshop → Submit Update**. (Same dialog as the
  initial upload, just routed at the existing Workshop ID.)
- Write a one-liner in the **Change notes** field — Workshop shows it on
  the item's page so users see what changed.

Subscribers don't need to do anything; Steam pulls the new files in the
background.

## Single Workshop item that drives all monitors (recommended)

Starting with v0.7.0+ the build also produces a **single combined WE
bundle** at `wallpaper_bridge/we_bundles_single/signalrgb-glow/`. Its
`project.json` declares a `screenIndex` user property (combo: *Screen 1
/ 2 / 3*), and the page's `wallpaperPropertyListener` calls
`setScreenIndex()` which transparently reconnects the WebSocket to the
matching `?screen=N` route on the bridge.

This means you can **publish ONE Workshop item** that subscribers assign
to every monitor they own, picking a different *Screen index* per
assignment in WE's properties panel. The bridge still routes the right
SignalRGB device's colours to each screen because it sees three distinct
WS connections, each with the right query param.

**To test before publishing:**

1. `pwsh installer/build.ps1` (or just run it manually — the single
   bundle is produced under step `[3a/5]`).
2. Copy `wallpaper_bridge/we_bundles_single/signalrgb-glow/` into Steam's
   `…\steamapps\common\wallpaper_engine\projects\myprojects\` (the
   installer's WE task currently only copies the three per-screen
   bundles; copy this one by hand for the test).
3. Restart Wallpaper Engine → it picks up the new "SignalRGB Glow" item
   under *My Wallpapers*.
4. Assign it to monitor 1. Open its properties panel — there's a new
   *Screen index* dropdown. Leave it on *Screen 1*.
5. Assign **the same wallpaper** to monitor 2. Set its *Screen index*
   to *Screen 2*.
6. Same for monitor 3 if you have one.
7. Make sure the bridge's *Number of screens* matches and that SignalRGB
   has the matching *Desktop Wallpaper - Screen N* devices placed on
   the canvas.

Each WE instance opens its own WS connection to the bridge with the
right `?screen=N` and gets its own glow feed. To verify: tint each
SignalRGB device differently and check the wallpapers light up
correctly.

**To publish the single item:**

Same flow as the three-per-screen items, but you only upload once:

1. Right-click *SignalRGB Glow* in WE → *Workshop → Share*.
2. Pre-filled title / description / tags from `project.json` are
   already Workshop-ready (the description explains the multi-monitor
   property setup).
3. Pick `workshop_preview.png` as the preview image.
4. Submit.

The three-per-screen bundles are still produced by the build for
backwards compatibility with the installer's auto-import (Lively users
benefit from per-screen titles in their Library) and for the legacy
*SignalRGB Glow - Screen 1/2/3* Workshop items if you ever want to
keep them. The single item is the cleaner Workshop story going
forward.

## What's automated, what's not

| Step | Automated? |
| --- | --- |
| Building the WE bundles | ✅ `installer/build.ps1` |
| Generating preview image | ✅ `installer/generate_workshop_preview.py` |
| Filling `project.json` (title, description, tags, preview path) | ✅ `installer/build.ps1` |
| Copying bundles into Steam's projects folder | ✅ installer's *"Install for Wallpaper Engine"* task |
| **Uploading to Workshop** | ❌ manual, ~5 min per item — no headless API for it |
| **Re-publishing after a bridge update** | ❌ also manual |

Workshop's UI flow is the only manual step. If volume ever grows enough to
justify it, [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD)
plus a `workshop_item.vdf` can drive uploads from the command line —
overkill for three items right now.
