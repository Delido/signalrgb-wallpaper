"""
generate_library.py

Procedural library of glow-ready wallpaper PNGs that ship with the
installer. Each PNG is a dark scene with transparent cut-outs the
SignalRGB glow shines through.

These are not curated artworks — they're meant as starter samples so
new users immediately see what the wallpaper does without having to
build their own first. Real artwork can be added later (manually
dropped into the library folder; the bridge picks it up via
LIBRARY_DIR enumeration regardless of whether this script produced it).

Run as part of installer/build.ps1 — output goes to
wallpaper_bridge/library/. Each entry is two files:
  <id>.png       — the wallpaper (1920×1080, sized for the smallest
                   common 16:9 panel; the wallpaper page upscales).
  <id>.thumb.png — 320×180 thumbnail for the Configurator's library
                   browser.

Plus library.json with the curated metadata (label, attribution).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H = 1920, 1080
TW, TH = 320, 180   # thumbnail
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "wallpaper_bridge" / "library"
# v1.7.5: curated WebP assets the build script copies into the library
# alongside the procedural set. These are git-tracked (unlike OUT_DIR
# which is gitignored as build output). Drop new <slug>.webp +
# <slug>.thumb.webp pairs into here to ship them with the installer;
# tools/process_starter_images.py generates them, tools/README.md
# documents the workflow.
CURATED_DIR = HERE / "assets" / "library"


def soft_window(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                color: tuple = (0, 0, 0, 0)) -> None:
    """Punch a rounded-rectangle hole. The glow layer behind shines
    through wherever alpha == 0."""
    draw.rounded_rectangle((x, y, x + w, y + h), radius=min(8, w // 4, h // 4),
                            fill=color)


def make_cyberpunk_skyline() -> Image.Image:
    """Night skyline: deep blue base, jagged building silhouettes,
    windows punched out as transparent rectangles for the glow."""
    img = Image.new("RGBA", (W, H), (8, 10, 22, 255))
    d = ImageDraw.Draw(img)
    rng = random.Random(0xC4FED4)
    # Distant skyline — flatter, lighter
    for i in range(30):
        x = i * (W // 30)
        bw = W // 30 + 4
        bh = rng.randint(180, 350)
        by = H - bh
        d.rectangle((x, by, x + bw, H), fill=(14, 18, 36, 255))
    # Foreground skyline — taller, darker, more windows
    for i in range(18):
        x = i * (W // 18) + rng.randint(-8, 8)
        bw = W // 18 + 6
        bh = rng.randint(380, 720)
        by = H - bh
        d.rectangle((x, by, x + bw, H), fill=(4, 6, 14, 255))
        # Window grid
        for wy in range(by + 30, H - 30, 28):
            for wx in range(x + 14, x + bw - 14, 22):
                if rng.random() < 0.45:
                    soft_window(d, wx, wy, 10, 14)
    return img


def make_neon_grid() -> Image.Image:
    """Synthwave grid: dark gradient sky, perspective grid floor with
    transparent grid lines. The horizon strip is wide-open so the glow
    forms a big sunset-style halo."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base = Image.new("RGBA", (W, H), (12, 6, 28, 255))
    # Subtle vertical gradient toward magenta on top
    for y in range(H // 2):
        a = y / (H / 2)
        col = (int(24 * (1 - a) + 12 * a),
               int(6  * (1 - a) + 4  * a),
               int(40 * (1 - a) + 28 * a), 255)
        ImageDraw.Draw(base).line([(0, y), (W, y)], fill=col)
    img.alpha_composite(base)
    d = ImageDraw.Draw(img)
    # Horizon glow strip — fully transparent so the glow shines through
    horizon_y = H // 2
    d.rectangle((0, horizon_y - 4, W, horizon_y + 28), fill=(0, 0, 0, 0))
    # Perspective grid below the horizon
    grid = Image.new("RGBA", (W, H - horizon_y), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    # Horizontal lines getting closer together near the horizon (top)
    for i in range(1, 14):
        t = (i / 14) ** 1.8
        y = int(t * (H - horizon_y))
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, 0), width=2)
    # Vanishing-point vertical lines
    vx = W // 2
    for i in range(-12, 13):
        end_x = vx + i * (W // 14)
        gd.line([(vx, 0), (end_x, H - horizon_y)], fill=(0, 0, 0, 0), width=2)
    img.alpha_composite(grid, (0, horizon_y))
    return img


def make_anime_window() -> Image.Image:
    """Single large round window looking out onto a starfield. The
    window itself + a few small portholes are transparent."""
    img = Image.new("RGBA", (W, H), (12, 14, 20, 255))
    d = ImageDraw.Draw(img)
    # Central round window — transparent
    cx, cy = W // 2, H // 2
    r = min(W, H) // 3
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 0))
    # Inner frame ring (opaque, dark)
    rr = r - 26
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(60, 50, 80, 255), width=8)
    # Small portholes top-left + bottom-right
    for (px, py, pr) in [(220, 200, 70), (W - 250, H - 230, 60),
                          (W - 360, 280, 50)]:
        d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(0, 0, 0, 0))
        d.ellipse((px - pr, py - pr, px + pr, py + pr),
                  outline=(48, 38, 64, 255), width=5)
    return img


def make_geometric_panels() -> Image.Image:
    """Tri-panel abstract: three vertical strips with different
    transparent geometric patterns inside. Works well on widescreen."""
    img = Image.new("RGBA", (W, H), (10, 12, 18, 255))
    d = ImageDraw.Draw(img)
    panel_w = W // 3
    # Panel 1: vertical bars
    for x in range(panel_w // 12, panel_w - 16, panel_w // 12):
        d.rectangle((x, 80, x + 14, H - 80), fill=(0, 0, 0, 0))
    # Panel 2: concentric squares
    cx, cy = panel_w + panel_w // 2, H // 2
    for s in range(60, min(panel_w, H) // 2 - 30, 60):
        d.rectangle((cx - s, cy - s, cx + s, cy + s),
                    outline=(0, 0, 0, 0), width=10)
    # Panel 3: diagonal hatching
    base_x = 2 * panel_w
    for off in range(-H, panel_w + H, 28):
        d.line([(base_x + off, 60), (base_x + off + H, 60 + H)],
               fill=(0, 0, 0, 0), width=6)
    # Subtle dividers
    d.line([(panel_w, 0), (panel_w, H)], fill=(28, 30, 44, 255), width=2)
    d.line([(2 * panel_w, 0), (2 * panel_w, H)], fill=(28, 30, 44, 255), width=2)
    return img


WALLPAPERS = [
    ("cyberpunk-skyline", "Cyberpunk skyline", make_cyberpunk_skyline),
    ("neon-grid",         "Neon grid",         make_neon_grid),
    ("anime-window",      "Anime round window", make_anime_window),
    ("geometric-panels",  "Geometric panels",  make_geometric_panels),
]


def _slug_to_label(slug: str) -> str:
    """Curated WebPs are filename-keyed; derive a human label from the
    slug. e.g. `cyberpunk-holo-street` -> `Cyberpunk Holo Street`."""
    return slug.replace("-", " ").replace("_", " ").title()


# v1.7.5: keyword -> tag map. Each curated slug gets every tag whose
# keyword appears in it. Designed for the Library tab's chip filter:
# the chips are sorted by frequency so the most useful filters bubble
# to the top automatically. Keep keywords lowercase + slug-friendly.
_TAG_RULES = {
    "cyberpunk":      ["cyberpunk", "neon", "night"],
    "neon":           ["neon", "night"],
    "aurora":         ["aurora", "nature", "night"],
    "synthwave":      ["synthwave", "retro"],
    "tokyo":          ["cyberpunk", "neon", "night", "asian"],
    "rgb":            ["rgb", "gaming", "interior"],
    "skyline":        ["skyline", "city"],
    "city":           ["city"],
    "street":         ["street", "city"],
    "alley":          ["street", "city"],
    "boulevard":      ["street", "city"],
    "backstreet":     ["street", "city"],
    "highway":        ["street", "city"],
    "storefront":     ["street", "city"],
    "vista":          ["city"],
    "holo":           ["cyberpunk", "futuristic"],
    "setup":          ["rgb", "gaming"],
    "studio":         ["rgb", "gaming"],
    "abstract":       ["abstract"],
    "curve":          ["abstract"],
    "geometric":      ["abstract"],
    "panels":         ["abstract"],
    "grid":           ["synthwave", "abstract"],
    "anime":          ["anime"],
    "window":         ["abstract"],
    "mountains":      ["synthwave", "nature"],
    "horizon":        ["synthwave"],
    "sun":            ["synthwave"],
    "pines":          ["nature"],
    "sky":            ["nature"],
    "night":          ["night"],
    "wet":            ["street", "city"],
    "pink":           ["neon"],
    # v1.7.5 part 2 themes:
    "underwater":     ["underwater", "nature"],
    "jellies":        ["underwater", "nature"],
    "sea":            ["underwater", "nature"],
    "bioluminescent": ["bioluminescent", "nature"],
    "mushroom":       ["bioluminescent", "nature"],
    "forest":         ["nature"],
    "grove":          ["nature"],
    "spaceship":      ["scifi", "futuristic", "interior"],
    "stellar":        ["scifi", "abstract"],
    "quantum":        ["abstract"],
    "plasma":         ["abstract"],
    "web":            ["abstract"],
    "burst":          ["abstract"],
    "wave":           ["abstract"],
    "twin":           ["cyberpunk", "city"],
    "towers":         ["cyberpunk", "city"],
    "cyan":           ["cyberpunk"],
    "magenta":        ["neon"],
    "foggy":          ["night"],
    "bridge":         ["scifi"],   # spaceship-bridge; cyberpunk-bridge-vista already picks up cyberpunk
    # v1.7.5 enrichment for Juggernaut-generated set:
    "curtain":        ["aurora", "nature"],
    "rainy":          ["street"],
    "futuristic":     ["futuristic", "scifi"],
}


def _tags_for_slug(slug: str) -> list[str]:
    """Derive a tag list from the slug's components. Order-preserving
    dedup; never returns duplicates. Returns [] for slugs that match
    no keywords (caller may still ship — tag chips just won't surface
    those items unless the user searches their label/id)."""
    parts = set(slug.lower().split("-"))
    tags: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for keyword, tag_list in _TAG_RULES.items():
            if keyword == part:
                for tg in tag_list:
                    if tg not in seen:
                        seen.add(tg)
                        tags.append(tg)
    return tags


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # v1.7.5: clean the output dir before regen so leftover files from a
    # previous build (different image set, or .png from before the WebP
    # switch) don't survive into the installer payload.
    for old in OUT_DIR.iterdir():
        if old.is_file():
            try: old.unlink()
            except OSError: pass

    catalogue = []
    # ── Procedural set ───────────────────────────────────────────
    # WebP at quality 88 — for our flat-colour geometric shapes this is
    # visually identical to lossless PNG at ~10 % the size.
    for slug, label, factory in WALLPAPERS:
        print(f"  generating {slug}...")
        img = factory()
        # Soften ragged transparency edges so the glow blur looks clean.
        # Tiny radius keeps shapes readable.
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
        out_path  = OUT_DIR / f"{slug}.webp"
        thumb_path = OUT_DIR / f"{slug}.thumb.webp"
        img.save(out_path, "WEBP", quality=88, method=6)
        img.copy().resize((TW, TH), Image.LANCZOS).save(
            thumb_path, "WEBP", quality=80, method=6)
        catalogue.append({
            "id":       slug,
            "label":    label,
            "file":     f"{slug}.webp",
            "thumb":    f"{slug}.thumb.webp",
            "w":        W,
            "h":        H,
            "category": "background",
            "tags":     _tags_for_slug(slug),
        })
    # ── Curated set ──────────────────────────────────────────────
    # Hand-picked images staged in installer/assets/library/. The build
    # copies them straight through — they're already saliency-processed
    # by tools/process_starter_images.py (or equivalent) so the alpha
    # mask is baked in. Pair each <slug>.webp with its <slug>.thumb.webp
    # if present, else fall back to the main file as its own thumb.
    if CURATED_DIR.exists():
        seen_stems = set()
        curated_files = sorted(CURATED_DIR.glob("*.webp"))
        all_names = {p.name for p in curated_files}
        # v1.7.5: skip thumb + 4K siblings in the main pass; they're
        # picked up as paired files for their parent slug below.
        for src in curated_files:
            if src.stem.endswith(".thumb") or src.stem.endswith(".4k"):
                continue
            slug = src.stem
            if slug in seen_stems:
                continue
            seen_stems.add(slug)
            dst = OUT_DIR / src.name
            dst.write_bytes(src.read_bytes())
            thumb_name = f"{slug}.thumb.webp"
            if thumb_name in all_names:
                (OUT_DIR / thumb_name).write_bytes(
                    (CURATED_DIR / thumb_name).read_bytes())
            else:
                thumb_name = src.name
            # v1.7.5: 4K sibling. Optional — if missing, library.json
            # entry just omits file4k and the Configurator falls back
            # to the FHD file for "Apply 4K" picks.
            file4k_name = f"{slug}.4k.webp"
            has_4k = file4k_name in all_names
            if has_4k:
                (OUT_DIR / file4k_name).write_bytes(
                    (CURATED_DIR / file4k_name).read_bytes())
            entry = {
                "id":       slug,
                "label":    _slug_to_label(slug),
                "file":     src.name,
                "thumb":    thumb_name,
                "w":        W,
                "h":        H,
                "category": "background",
                "tags":     _tags_for_slug(slug),
            }
            if has_4k:
                entry["file4k"] = file4k_name
            catalogue.append(entry)
        print(f"  copied {len(seen_stems)} curated WebP(s) from "
              f"{CURATED_DIR.relative_to(HERE.parent)}/")

    cat_path = OUT_DIR / "library.json"
    cat_path.write_text(json.dumps({"version": 1, "items": catalogue}, indent=2),
                         encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT_DIR.iterdir())
    print(f"  wrote {len(catalogue)} wallpapers + thumbnails + library.json "
          f"({total // 1024} KB total)")


if __name__ == "__main__":
    main()
