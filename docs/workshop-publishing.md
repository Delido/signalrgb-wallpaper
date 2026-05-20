# Publishing to Steam Workshop

This is a cheatsheet for the maintainer (Sebastian) — the step-by-step
for pushing the single **SignalRGB Glow** wallpaper to the [Wallpaper
Engine Steam Workshop](https://steamcommunity.com/app/431960/workshop/).
The bundle is already produced by `installer/build.ps1`; the rest is a
UI flow inside Wallpaper Engine.

> Starting with v0.7.2-beta the build emits **one** combined WE bundle
> with a *Screen index* user property. Subscribers assign that single
> item to every monitor they want to drive and pick a different *Screen
> index* per assignment. The four per-screen bundles from earlier
> builds (`SignalRGB_Glow_Screen{1..4}`) are gone — the single bundle
> covers every use case.

## Prerequisites

- A Steam account that owns Wallpaper Engine.
- The bundle built locally: run `pwsh installer/build.ps1` once and
  confirm `wallpaper_bridge/we_bundles_single/signalrgb-glow/` contains:
  - `index.html`
  - `project.json` (the WE manifest — title, BBCode description, tags,
    `screenIndex` combo property with options *Screen 1* / *Screen 2*
    / *Screen 3* / *Screen 4*)
  - `interact.min.js` + `interact.LICENSE.txt`
  - `thumbnail.png`
  - `workshop_preview.png` (1920 × 1080 — the listing image Workshop
    browses)

The installer's *"Install for Wallpaper Engine"* task copies this
folder into Steam's
`steamapps\common\wallpaper_engine\projects\myprojects\signalrgb-glow\`
for you. You can also drop the folder there manually.

## Test locally before publishing

1. `pwsh installer/build.ps1` (the single bundle is produced under
   step `[3a/5]`).
2. Make sure the installer's WE task ran (or copy
   `wallpaper_bridge/we_bundles_single/signalrgb-glow/` into Steam's
   `…\steamapps\common\wallpaper_engine\projects\myprojects\` by hand).
3. Restart Wallpaper Engine → it picks up **SignalRGB Glow** under
   *My Wallpapers*.
4. Assign it to monitor 1. Open its properties panel — there's a
   *Screen index* dropdown. Leave it on *Screen 1*.
5. Assign **the same wallpaper** to monitor 2. Set its *Screen index*
   to *Screen 2*.
6. Same for monitor 3 / 4 if you have them.
7. Make sure the bridge's *Number of screens* matches and that
   SignalRGB has the matching *Desktop Wallpaper - Screen N* devices
   placed on the canvas.

Each WE instance opens its own WS connection to the bridge with the
right `?screen=N` and gets its own glow feed. To verify: tint each
SignalRGB device differently and check the wallpapers light up
correctly.

## Upload flow (~5 min, one-time)

1. Open **Wallpaper Engine** on Steam.
2. Tab **Workshop** → **Manage** → **My Wallpapers**. *SignalRGB Glow*
   is in the list.
3. Right-click it → **Workshop → Share**. WE opens its upload panel.
4. Fill in:
   - **Title:** pre-filled from `project.json` ("SignalRGB Glow").
     Leave as-is.
   - **Description:** pre-filled from `project.json` (BBCode, with
     bridge requirement + GitHub link prominently up top, including
     the multi-monitor *Screen index* explanation). Review once for
     typos.
   - **Tags:** pre-filled from `project.json` (`RGB`, `Customizable`,
     `Web`, `Abstract`, `Multi-Monitor`). Workshop will show its own
     tag picker; you can add more if relevant.
   - **Preview image:** Workshop wants its own preview file. Click
     **Browse** and pick `workshop_preview.png` from the bundle folder
     (`…\myprojects\signalrgb-glow\workshop_preview.png`).
   - **Visibility:** **Public** for general release. Use **Friends**
     or **Private** for a soft-launch / a friend-test.
   - **Change notes** (only on later uploads): explain what's new.
5. Accept the Steam Workshop Terms (only the very first upload of
   your life).
6. Hit **Submit**. Steam processes for ~30–60 s, then a "View in
   browser" button appears.

The item gets a Workshop ID (large integer in the URL).

## After upload — quality-of-life

- **Pin a screenshot** of the wallpaper actually running (cutouts and
  live glow) once you have one. The procedural `workshop_preview.png`
  is good for first-launch but a real screenshot is more convincing.
- Set the **License field** to *MIT* (Workshop UI dropdown) for
  clarity.

## Re-publishing after a bridge update

Every time the bridge is re-released (= new build of
`installer/build.ps1`) the `index.html` inside the WE bundle changes.
Subscribed users get the new HTML the next time they restart Wallpaper
Engine — **only if you republish the Workshop item**.

- Workshop pulls from the same
  `…\myprojects\signalrgb-glow\` folder you uploaded from. Make sure
  that folder has the freshly-built files (the installer task
  overwrites in place).
- In WE: **Workshop → Manage → My Wallpapers** → right-click *SignalRGB
  Glow* → **Workshop → Submit Update**. (Same dialog as the initial
  upload, just routed at the existing Workshop ID.)
- Write a one-liner in the **Change notes** field — Workshop shows it
  on the item's page so users see what changed.

Subscribers don't need to do anything; Steam pulls the new files in
the background.

## A note on the legacy per-screen design

Builds v0.5.2-beta → v0.7.1-beta produced four per-screen WE bundles
(*SignalRGB Glow - Screen 1 / 2 / 3 / 4*) — that was the workaround
before user properties were wired up. Those items were never actually
published to the Steam Workshop, so there's nothing to retire in the
Workshop UI. The single-bundle approach below is the only thing that
ever needs to live on Workshop.

## What's automated, what's not

| Step | Automated? |
| --- | --- |
| Building the WE bundle | ✅ `installer/build.ps1` |
| Generating preview image | ✅ `installer/generate_workshop_preview.py` |
| Filling `project.json` (title, description, tags, screenIndex options) | ✅ `installer/build.ps1` |
| Copying the bundle into Steam's projects folder | ✅ installer's *"Install for Wallpaper Engine"* task |
| **Uploading to Workshop** | ❌ manual, ~5 min — no headless API for it |
| **Re-publishing after a bridge update** | ❌ also manual |

Workshop's UI flow is the only manual step. With a single item the
manual cost is now flat regardless of how many monitors the user has.
If volume ever grows enough to justify it,
[SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD) plus a
`workshop_item.vdf` can drive uploads from the command line — overkill
for one item.
