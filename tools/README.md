# Starter image curation

This folder holds the tooling to add new wallpaper images to the
bundled starter library at `wallpaper_bridge/library/`. End users
see these images in the Configurator's Background card as
click-to-apply tiles.

## Workflow

### 1. Find candidates

Stick to these sources — all permit redistribution without
attribution:

| Source | License | Search URL |
|---|---|---|
| Unsplash | [Unsplash License](https://unsplash.com/license) (commercial use OK, no attribution required) | <https://unsplash.com/s/photos/> |
| Pexels | [Pexels License](https://www.pexels.com/license/) (commercial use OK, no attribution required) | <https://www.pexels.com/search/> |
| Pixabay | [Pixabay Content License](https://pixabay.com/service/license-summary/) (commercial use OK, attribution appreciated) | <https://pixabay.com/images/search/> |

**Do NOT** pick from Wikimedia Commons (most images require
CC-BY attribution that we don't ship), Pinterest (no clear
licensing), Reddit (random uploads), Google Image Search (mix of
everything), or Midjourney / DALL·E / ChatGPT (TOS is ambiguous
on redistributable assets).

### 2. Search terms that work well

Glow-driven wallpapers need a **dark backdrop with bright
glow-coloured regions** — the saliency mask carves out the
bright bits and SignalRGB shines through. The following
searches reliably return that look:

- `cyberpunk neon city night`
- `synthwave neon grid`
- `futuristic gaming setup rgb`
- `tokyo street neon rain`
- `dark abstract neon waves`
- `ultrawide cyberpunk`
- `neon arcade interior`
- `dark room rgb monitor glow`
- `nightclub neon lights`
- `space station interior lights`
- `aurora borealis dark sky`
- `bioluminescent forest night`

Filter results to landscape orientation, ideally ≥3840×2160 so
the resize-and-crop has room to work without quality loss.

### 3. Drop files into `starter-images-in/`

Filename → label + slug — see [process_starter_images.py](process_starter_images.py)
for the rules. `Cyberpunk Skyline At Night.jpg` becomes
`cyberpunk-skyline-at-night` (slug) + `Cyberpunk skyline at night`
(label). Override with a sidecar `<file>.meta` if needed:

```text
label: Tokyo Backstreets
slug:  tokyo-backstreets
```

### 4. Run the processor

```bash
python tools/process_starter_images.py
```

Outputs land in `wallpaper_bridge/library/`:

- `<slug>.png` — 1920×1080 (default) with alpha mask
- `<slug>.thumb.png` — 320×180 preview
- `library.json` — appended / updated entry

Flags:

- `--slider 60` — bias the saliency cutoff (0..100, default 50;
  higher cuts more, lower preserves more of the source)
- `--width 5120 --height 1440` — render ultrawide instead of
  default 1080p
- `--dry-run` — list what would happen without writing anything

### 5. Review the output

Open the generated `.png` in any image viewer that supports
transparency (Krita, GIMP, IrfanView with the alpha plugin,
Windows Photos). The bright glow-coloured regions should be
transparent (checkerboard); the dark backdrop should be opaque.

If the cut is too aggressive (wide swaths of the image gone),
re-run with `--slider 35`. Too conservative (no transparency at
all where you wanted it), re-run with `--slider 65`. Each image
can have its own slider — process them one at a time if you
want per-image control.

### 6. Commit

The processed `.png` + `.thumb.png` + updated `library.json`
under `wallpaper_bridge/library/` are what ships in the
installer. The raw source files in `tools/starter-images-in/`
are gitignored — keep them locally for re-processing but they
don't need to go into git.

## Attribution

If you ever add a Wikimedia / Flickr CC-BY image (only when you
explicitly need it — most CC0 sources cover us), add the credit
line to [docs/credits.md](../docs/credits.md) **before** running
the processor. The bundled `library.json` itself has no
attribution field; we rely on the credits doc.

## Image generation as an alternative

For a curated branded series, run Stable Diffusion / SDXL / Flux
locally (ComfyUI is the typical wrapper). Outputs from
foundation models are not copyright-eligible in the US
(*Thaler v. Perlmutter*, 2023), so you can ship them freely as
long as the model license permits it:

- **Apache 2.0** — Flux.1-schnell ✅
- **CreativeML OpenRAIL-M** — SDXL base ✅
- **Stability NC** — SD3 medium ❌ (non-commercial only)

A starter prompt library lives in [docs/asset-prompts.md](../docs/asset-prompts.md)
(create that doc when you start the AI track — currently empty
placeholder territory).
