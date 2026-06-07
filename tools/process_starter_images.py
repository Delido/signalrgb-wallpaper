"""Curate + transparency-process starter library images.

Workflow
--------
1. Pick photos (Unsplash / Pexels / Pixabay CC0 — see README.md in
   this folder for search-term suggestions).
2. Drop the raw files (PNG / JPG / WebP) into
   `tools/starter-images-in/`.
3. Run: `python tools/process_starter_images.py`.
4. Outputs land in `wallpaper_bridge/library/`:
     - `<slug>.png`         — full-res w/ alpha mask
     - `<slug>.thumb.png`   — 320x180 preview thumb
     - `library.json`       — appended / updated entry per image

The transparency mask is a Python port of the Builder's
`computeAutoSaliency()` function (Achanta et al. 2009,
frequency-tuned saliency, public-domain algorithm). Glow-bright
regions -> transparent so SignalRGB colours shine through; dark
backdrop -> opaque.

Re-runs are idempotent — re-processing the same input file overwrites
the prior `<slug>.png` and updates the library.json entry in place.

Naming
------
Filename -> slug. `Cyberpunk Skyline At Night.jpg` becomes
`cyberpunk-skyline-at-night`. Label is the filename stem with
hyphens turned back into spaces + each word title-cased.

Override either by adding a YAML-ish sidecar `<file>.meta`:

    label: My Custom Name
    slug:  my-custom-slug

(Optional. Defaults from the filename are fine for most.)

Sources note
------------
Every shipped image MUST be CC0 / Unsplash / Pexels / Pixabay /
self-generated. The shipping bundle goes through `library.json`
which the bridge serves at `/library/list` to end users; we never
distribute a rights-encumbered photo.

If a photo's license requires attribution (Pexels does NOT, Unsplash
does NOT, Pixabay does NOT — Wikimedia CC-BY DOES), add the
attribution to `docs/credits.md` BEFORE running this script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
IN_DIR  = ROOT / "tools" / "starter-images-in"
# v1.7.5: switched output to the curated staging dir (git-tracked,
# WebP, what generate_library.py copies into the installer bundle).
# The previous target — wallpaper_bridge/library/ — is the runtime
# dir, regenerated on every build. Writing there worked but meant
# manual WebP conversion + manual copy as a follow-up step. Going
# direct to installer/assets/library/ makes one command produce the
# shippable artefact.
OUT_DIR = ROOT / "installer" / "assets" / "library"
THUMB_W = 320
# Quality settings match the manual heredoc conversion used for the
# v1.7.5 first cut: main slightly higher because the saliency-cut
# regions need clean edges; thumb a touch lower because it's a
# preview at 320 px.
WEBP_QUALITY_MAIN  = 88
WEBP_QUALITY_THUMB = 80

VALID_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


# ── slug + meta helpers ──────────────────────────────────────────

def slugify(stem: str) -> str:
    """Filename stem -> URL-safe slug.
    'Cyberpunk Skyline At Night' -> 'cyberpunk-skyline-at-night'."""
    s = unicodedata.normalize("NFKD", stem)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "wallpaper"


def labelify(stem: str) -> str:
    """Filename stem -> human-readable label.
    'cyberpunk-skyline-at-night' -> 'Cyberpunk skyline at night'.
    Keeps the first word capitalised, rest lowercase — matches the
    existing library.json style (e.g. "Cyberpunk skyline")."""
    s = re.sub(r"[_-]+", " ", stem).strip()
    if not s:
        return "Wallpaper"
    return s[0].upper() + s[1:].lower()


def read_meta_sidecar(src: Path) -> dict:
    """Optional `<file>.meta` carries label / slug overrides.
    Format is plain `key: value` lines — one per line, # for
    comments. Missing file -> empty dict."""
    sidecar = src.with_suffix(src.suffix + ".meta")
    if not sidecar.exists():
        return {}
    out: dict = {}
    for line in sidecar.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip().lower()] = v.strip()
    return out


# ── saliency -> alpha mask ────────────────────────────────────────

def compute_alpha_mask(rgb: np.ndarray, slider: int = 50,
                       *, soft: bool = True) -> np.ndarray:
    """Python port of `computeAutoSaliency()` in builder.html.

    Achanta et al. 2009 frequency-tuned saliency:
      score = ‖pixel - mean_rgb‖₂ + max(0, lum - mean_lum) * 0.6

    Threshold at `smax * (0.85 - slider/100 * 0.7)` — default
    slider=50 cuts the top half of salient mass, which on glowy
    wallpapers carves out the neon / panel / window regions and
    leaves the dark backdrop intact.

    Returns a uint8 mask the same shape as the HxW input — 0 for
    "opaque backdrop", 255 for "transparent glow region"."""
    H, W, _ = rgb.shape
    flat = rgb.reshape(-1, 3).astype(np.float32)
    # Per-pixel luminance with the same 0.299/0.587/0.114 weights
    # the JS path uses (BT.601 luma).
    lum = flat @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    mean_rgb = flat.mean(axis=0)
    mean_lum = float(lum.mean())
    delta = flat - mean_rgb
    colour_dist = np.sqrt((delta * delta).sum(axis=1))
    lum_boost = np.maximum(0.0, lum - mean_lum) * 0.6
    score = (colour_dist + lum_boost).reshape(H, W)
    smax = float(score.max())
    if smax <= 0:
        # Pathological all-one-colour image - nothing to cut.
        return np.zeros((H, W), dtype=np.uint8)
    cutoff = smax * (0.85 - slider / 100.0 * 0.7)
    if not soft:
        return (score >= cutoff).astype(np.uint8) * 255
    # v1.7.5: soft linear ramp around the cutoff instead of a hard
    # binary threshold. Half-width = 5% of smax so the band covers
    # 10% total - wide enough to give edges a few semi-transparent
    # pixels at full-res, narrow enough that we don't bleed glow
    # into the backdrop. Then morphological close (dilate->erode)
    # fills small holes inside neon-sign regions so a "BAR" sign
    # body gets cut as a whole shape, not just its hottest pixels.
    # Finally a Gaussian blur smooths the edge.
    ramp_half = smax * 0.05
    mask = np.clip((score - (cutoff - ramp_half)) / (2 * ramp_half),
                   0.0, 1.0)
    mask = (mask * 255).astype(np.uint8)
    pil_mask = Image.fromarray(mask, mode="L")
    pil_mask = pil_mask.filter(ImageFilter.MaxFilter(5))   # dilate
    pil_mask = pil_mask.filter(ImageFilter.MinFilter(5))   # erode
    pil_mask = pil_mask.filter(ImageFilter.GaussianBlur(radius=2))
    return np.asarray(pil_mask)


def apply_mask(img: Image.Image, slider: int) -> Image.Image:
    """Run saliency on `img`, return a new RGBA image where the
    mask's 255-pixels become alpha=0 (transparent glow) and 0-pixels
    stay alpha=255 (opaque backdrop)."""
    rgb = np.asarray(img.convert("RGB"))
    mask_transparent = compute_alpha_mask(rgb, slider=slider)
    alpha = 255 - mask_transparent
    rgba = np.dstack([rgb, alpha])
    return Image.fromarray(rgba, mode="RGBA")


# ── library.json upsert ──────────────────────────────────────────

def load_library_json(p: Path) -> dict:
    if not p.exists():
        return {"version": 1, "items": []}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {"version": 1, "items": []}


def upsert_entry(catalogue: dict, entry: dict) -> None:
    """Update by `id` if present, else append. Keeps the existing
    pinned / order fields if the entry already lived in the
    catalogue."""
    items = catalogue.setdefault("items", [])
    for i, it in enumerate(items):
        if it.get("id") == entry["id"]:
            preserved = {k: it[k] for k in ("pinned", "order", "addedAt",
                                             "category")
                         if k in it}
            entry = {**entry, **preserved}
            items[i] = entry
            return
    items.append(entry)


# ── main ─────────────────────────────────────────────────────────

def process_one(src: Path, slider: int, *,
                target_w: int, target_h: int) -> dict:
    """Read `src`, resize-and-crop to target dimensions, apply
    saliency-driven alpha, write `<slug>.png` + `<slug>.thumb.png`
    into OUT_DIR, return the library.json entry."""
    meta = read_meta_sidecar(src)
    slug = meta.get("slug") or slugify(src.stem)
    label = meta.get("label") or labelify(src.stem)
    img = Image.open(src)
    # Cover-fit crop to the target ratio so we don't introduce empty
    # bars on non-target aspect inputs. Use Lanczos for the resize
    # because we're dropping resolution -> quality matters.
    src_ar = img.width / img.height
    tgt_ar = target_w / target_h
    if src_ar > tgt_ar:
        # Source wider: crop horizontally to match target ratio.
        new_w = int(img.height * tgt_ar)
        ox = (img.width - new_w) // 2
        img = img.crop((ox, 0, ox + new_w, img.height))
    elif src_ar < tgt_ar:
        new_h = int(img.width / tgt_ar)
        oy = (img.height - new_h) // 2
        img = img.crop((0, oy, img.width, oy + new_h))
    img_fhd = img.resize((target_w, target_h), Image.LANCZOS)
    rgba_fhd = apply_mask(img_fhd, slider)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # v1.7.5: WebP with alpha. Quality 88 keeps the saliency edges
    # clean; ~85% smaller than PNG with the soft-ramp mask intact.
    out_full = OUT_DIR / f"{slug}.webp"
    rgba_fhd.save(out_full, format="WebP",
                  quality=WEBP_QUALITY_MAIN, method=6)
    thumb_h = round(THUMB_W * target_h / target_w)
    thumb = rgba_fhd.resize((THUMB_W, thumb_h), Image.LANCZOS)
    out_thumb = OUT_DIR / f"{slug}.thumb.webp"
    thumb.save(out_thumb, format="WebP",
               quality=WEBP_QUALITY_THUMB, method=6)
    # v1.7.5: 4K variant. LANCZOS upscale the RGB then re-run
    # saliency at 4K so the alpha mask aligns with the upscaled
    # pixels (resizing an FHD alpha would soften the edges).
    # Quality stays at 88 — at 4K the soft-ramp mask + cover-fit
    # neon glow burn through any lower quality.
    img_4k  = img.resize((target_w * 2, target_h * 2), Image.LANCZOS)
    rgba_4k = apply_mask(img_4k, slider)
    out_4k  = OUT_DIR / f"{slug}.4k.webp"
    rgba_4k.save(out_4k, format="WebP",
                 quality=WEBP_QUALITY_MAIN, method=6)
    size_full  = out_full.stat().st_size
    size_thumb = out_thumb.stat().st_size
    size_4k    = out_4k.stat().st_size
    print(f"  -> {out_full.name}  ({size_full / 1024:.0f} KB)  "
          f"+ {out_thumb.name}  ({size_thumb / 1024:.0f} KB)  "
          f"+ {out_4k.name}  ({size_4k / 1024:.0f} KB)")
    return {
        "id":    slug,
        "label": label,
        "file":  out_full.name,
        "thumb": out_thumb.name,
        "file4k": out_4k.name,
        "w":     target_w,
        "h":     target_h,
        "category": "background",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slider", type=int, default=50,
        help="Saliency cutoff bias 0..100 (default 50). Higher = "
             "cut more, lower = cut less. The Builder's default in "
             "the UI is also 50.")
    parser.add_argument(
        "--width", type=int, default=1920,
        help="Target full-res width (default 1920).")
    parser.add_argument(
        "--height", type=int, default=1080,
        help="Target full-res height (default 1080).")
    parser.add_argument(
        "--input-dir", type=Path, default=IN_DIR,
        help=f"Folder with raw input images (default {IN_DIR}).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be processed, don't write anything.")
    args = parser.parse_args()

    in_dir: Path = args.input_dir
    if not in_dir.exists():
        print(f"No input folder: {in_dir}", file=sys.stderr)
        return 2
    sources = [p for p in sorted(in_dir.iterdir())
               if p.suffix.lower() in VALID_EXT]
    if not sources:
        print(f"No images to process in {in_dir}.\n"
              f"Drop PNG / JPG / WebP files in there and re-run.",
              file=sys.stderr)
        return 1

    print(f"Found {len(sources)} image(s) in {in_dir.name}/. "
          f"Target {args.width}x{args.height}, "
          f"saliency slider {args.slider}.")

    if args.dry_run:
        for src in sources:
            slug = slugify(src.stem)
            print(f"  (dry) {src.name}  ->  {slug}.png")
        return 0

    # v1.7.5: no library.json upsert here. The shipping catalogue is
    # written by installer/generate_library.py at build time (which
    # also handles tag derivation from slugs). At dev-runtime the
    # bridge's _library_rebuild_catalogue scans the live directory
    # and (re)constructs the catalogue on the fly.
    for src in sources:
        print(f"Processing {src.name} ...")
        process_one(src, args.slider,
                    target_w=args.width,
                    target_h=args.height)

    print(f"\nWrote {len(sources)} curated asset(s) to "
          f"{OUT_DIR.relative_to(ROOT)}/.\n"
          f"Build the installer to bundle them: "
          f"installer\\build.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
