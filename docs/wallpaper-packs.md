# Wallpaper Packs

Themed wallpaper bundles you can install into the Library tab in a
single click.

## How it works

The Configurator's **Library** tab has a **📦 Wallpaper packs**
section at the bottom. Open it and the bridge fetches a manifest
from this docs site
([library-packs.json](library-packs.json)) listing every available
pack — name, description, image count, total download size, and a
SHA-256 of the ZIP.

Click **Load** on a pack and the bridge:

1. Downloads the pack ZIP from the
   [`library-packs-v1`](https://github.com/Delido/signalrgb-wallpaper/releases/tag/library-packs-v1)
   GitHub release.
2. SHA-256-verifies the downloaded bytes against the digest in the
   manifest. Mismatch → install aborts, ZIP deleted.
3. Walks every entry in the ZIP before extracting anything and
   **refuses any non-image entry** (`.exe`, `.dll`, `.bat`, `.ps1`,
   …). A pack can only ever drop image files (`.webp`, `.png`,
   `.jpg`, `.gif`, `.bmp`, `.avif`) on disk.
4. Extracts the images into
   `%LOCALAPPDATA%\SignalRGBWallpaper\library\` and rebuilds the
   library catalogue. Tiles appear in your Library grid
   immediately.

All four steps run server-side in the bridge's executor pool — the
Configurator stays responsive during the download.

## Available packs

Currently 13 packs, each containing 9 – 17 1920×1080 wallpapers
(plus 4K + thumbnail siblings). Total catalogue around 400 MB if
you install everything; individual packs are ~9 – 52 MB.

| Pack | Theme |
| --- | --- |
| Aurora | Northern lights, mountains, atmospheric skies |
| Blockbuster | Cinematic hero scenes |
| Crystal | Crystalline structures, gem facets |
| Cyberpunk | Neon megacities, holographic streets |
| Energy | Electric arcs, plasma fields, high-voltage abstract |
| Film | Cinematic stills, atmospheric movie compositions |
| Fireworks | Burst, sparkle, trail pyrotechnic light |
| Forest | Mystical woodlands, glowing canopies |
| Magic | Fantasy arcane glow, magical runes |
| Space | Deep-space nebulae, stellar bursts |
| Synthwave | Retro 80s grids, neon mountains, chrome horizons |
| Underwater | Bioluminescent deep-sea creatures, kelp forests |
| Video Games | Game-style scenes — fantasy castles, sci-fi vistas |

## Why is this different from v2.0.x?

v2.0.0 had an in-app pack downloader. v2.0.1 ripped it out because
Windows Defender's ML heuristic flagged the
`urlopen + zipfile.extractall` pattern on the (then-unsigned)
bridge as `Wacatac.B!ml`. The combination *unsigned bridge in
user-writable `%LOCALAPPDATA%`* + *downloads binary content into
its own neighbourhood* triggered classifiers that look for the
"loader → payload" pattern of real malware.

v2.3.0-beta reintroduces the in-app installer with the v2.2.x
mitigations in place:

- **Bridge moved to `C:\Program Files`** (v2.2.1). Admin-only ACL,
  not a user-writable persistence location.
- **User-triggered downloads only** — opening the section and
  clicking **Load** on a specific pack. No background polling for
  the pack manifest, no auto-installation.
- **Manifest hosted on GitHub Pages** (this docs site) rather than
  raw.githubusercontent.com — Pages traffic looks like normal docs
  fetches to AV / firewall heuristics.
- **Image-extension whitelist enforced before extraction**. The
  bridge inspects every ZIP entry up front; any non-image extension
  aborts the install. The extracted footprint is provably "image
  data only", which is much harder to classify as loader-shaped.
- **SHA-256 verification** of every downloaded ZIP against the
  manifest digest.

If Defender still flags the download on your machine, the
[browse packs on GitHub](https://github.com/Delido/signalrgb-wallpaper/releases/tag/library-packs-v1)
fallback is one click away — same ZIPs, manual extract into
`%LOCALAPPDATA%\SignalRGBWallpaper\library\`, same end result.

## Licensing

Every pack carries its full generator + license chain in the
manifest. Current packs were all produced with the same workflow:

- **Image generation** —
  [Juggernaut XL v9](https://civitai.com/models/133005/juggernaut-xl)
  (RunDiffusion Photo v2), under the CreativeML Open RAIL-M license
  plus the RunDiffusion addendum.
- **4K upscale** —
  [4xNomos8kDAT](https://huggingface.co/Phips/4xNomos8kDAT) by
  Philip Hofmann (Phips), CC-BY-4.0.

Pack contents are redistributable as MIT-compatible material — you
can use them in personal wallpapers, streams, screenshots, etc.
without further attribution. The manifest entries spell out the
chain in machine-readable form for anyone who needs it.
