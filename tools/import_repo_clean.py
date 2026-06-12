"""
One-shot importer for the v1.7.5 wave 2 batch — 112 license-clean
4K RGBA wallpapers produced under ComfyUI with Juggernaut XL v9
+ 4xNomos8kDAT (CC-BY-4.0). Replaces the prior installer/assets/
library/ + installer/packs/ contents wholesale.

Pipeline per source:
  source (3840x2160 RGBA, luminance-alpha baked in)
    -> <slug>.4k.webp      (encode-only, no resize)
    -> <slug>.webp         (Lanczos -> 1920x1080)
    -> <slug>.thumb.webp   (Lanczos -> 320x180)

Skips the Achanta saliency pass — input already carries an alpha
mask, double-processing would mangle the edges.

Layout produced:
  installer/assets/library/     6 essentials (visual breadth picks)
  installer/packs/cyberpunk-synthwave/   18 images
  installer/packs/nature/                28 images
  installer/packs/cosmic/                29 images
  installer/packs/fx/                    19 images
  installer/packs/cinema-games/          12 images
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(r"C:\Users\smend\ComfyUI-Shared\output\repo_clean")
ESSENTIALS_DIR = ROOT / "installer" / "assets" / "library"
PACKS_DIR = ROOT / "installer" / "packs"

# Source categories — pack id == category. Index 1 of each category
# is promoted to ESSENTIALS so the installer ships at least one tile
# per theme; indices 2..N (or 1..N for categories that contribute no
# essential) make up the pack.
CATEGORY_SIZES = {
    "aurora":      10,
    "blockbuster":  4,
    "crystal":     10,
    "cyberpunk":   10,
    "energy":      10,
    "film":         4,
    "fireworks":   10,
    "forest":      10,
    "magic":       10,
    "space":       10,
    "synthwave":   10,
    "underwater":  10,
    "videospiele":  4,
}

# Categories that contribute their first slug to the installer's
# essentials set. Six picks for visual breadth without inflating
# the installer; the rest stays in their own pack.
ESSENTIAL_CATEGORIES = {"cyberpunk", "aurora", "forest", "space",
                        "synthwave", "crystal"}

ESSENTIALS = [(cat, 1) for cat in sorted(ESSENTIAL_CATEGORIES)]

# pack_id -> [(category, index)]. One pack per category. Categories
# in ESSENTIAL_CATEGORIES skip index 1 (it lives in essentials).
PACK_LAYOUT = {}
for cat, n in CATEGORY_SIZES.items():
    start = 2 if cat in ESSENTIAL_CATEGORIES else 1
    PACK_LAYOUT[cat] = [(cat, i) for i in range(start, n + 1)]

THUMB_W, THUMB_H = 320, 180
FHD_W, FHD_H     = 1920, 1080
WEBP_MAIN_Q  = 88
WEBP_THUMB_Q = 80


def slug_for(category: str, idx: int) -> str:
    return f"{category}-{idx:02d}"


def source_for(category: str, idx: int) -> Path:
    """ComfyUI emits files like cyberpunk_00001_.png."""
    return SOURCE / category / f"{category}_{idx:05d}_.png"


def encode_variant(img: Image.Image, dst: Path, *, quality: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, format="WebP", quality=quality, method=6)


def process(category: str, idx: int, target_dir: Path) -> None:
    slug = slug_for(category, idx)
    src = source_for(category, idx)
    if not src.exists():
        raise FileNotFoundError(src)
    im = Image.open(src).convert("RGBA")
    # 4K — encode-only, no resize.
    encode_variant(im, target_dir / f"{slug}.4k.webp", quality=WEBP_MAIN_Q)
    # FHD via Lanczos. Source is exactly 2:1 of FHD, so no aspect drift.
    fhd = im.resize((FHD_W, FHD_H), Image.LANCZOS)
    encode_variant(fhd, target_dir / f"{slug}.webp", quality=WEBP_MAIN_Q)
    # Thumb keeps same aspect.
    thumb = im.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    encode_variant(thumb, target_dir / f"{slug}.thumb.webp", quality=WEBP_THUMB_Q)


def _onerror(func, path, exc_info) -> None:
    # OneDrive likes to hold transient ReparsePoint / read-only flags
    # on freshly-touched dirs. Clear the read-only bit and retry once;
    # if it still fails we surface the error.
    import os
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise


def wipe(directory: Path) -> None:
    if not directory.exists():
        return
    for p in directory.iterdir():
        if p.is_file():
            try:
                p.unlink()
            except PermissionError:
                _onerror(p.unlink, p, None)
        elif p.is_dir():
            shutil.rmtree(p, onexc=_onerror)


def main() -> int:
    if not SOURCE.exists():
        print(f"source missing: {SOURCE}", file=sys.stderr)
        return 2
    print(f"source: {SOURCE}")
    print(f"essentials -> {ESSENTIALS_DIR.relative_to(ROOT)}/")
    print(f"packs      -> {PACKS_DIR.relative_to(ROOT)}/")

    # 1. Wipe the prior wave's content. Source-of-truth is whatever
    #    repo_clean ships now; preserving stale slugs would muddle
    #    the catalogue.
    print("\nwiping prior content…")
    wipe(ESSENTIALS_DIR)
    wipe(PACKS_DIR)
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    ESSENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Essentials.
    print("\nprocessing essentials…")
    for cat, idx in ESSENTIALS:
        process(cat, idx, ESSENTIALS_DIR)
        print(f"  + {slug_for(cat, idx)}")

    # 3. Packs.
    for pack_id, items in PACK_LAYOUT.items():
        out_dir = PACKS_DIR / pack_id
        print(f"\nprocessing pack {pack_id} ({len(items)} images)…")
        for cat, idx in items:
            process(cat, idx, out_dir)
            print(f"  + {slug_for(cat, idx)}")

    # 4. Summary.
    total_kb = 0
    print("\n--- summary ---")
    for d in [ESSENTIALS_DIR, *sorted(PACKS_DIR.iterdir())]:
        if not d.is_dir(): continue
        size = sum(p.stat().st_size for p in d.iterdir()) // 1024
        total_kb += size
        slugs = len({p.stem.replace(".thumb", "").replace(".4k", "")
                      for p in d.iterdir() if p.suffix == ".webp"})
        print(f"  {d.relative_to(ROOT):42s}  {slugs:3d} slugs   {size:6d} KB")
    print(f"  {'TOTAL':42s}  ------    {total_kb:6d} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
