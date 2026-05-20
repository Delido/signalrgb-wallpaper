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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    catalogue = []
    for slug, label, factory in WALLPAPERS:
        print(f"  generating {slug}…")
        img = factory()
        # Soften ragged transparency edges so the glow blur looks clean.
        # Tiny radius keeps shapes readable.
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
        out_path  = OUT_DIR / f"{slug}.png"
        thumb_path = OUT_DIR / f"{slug}.thumb.png"
        img.save(out_path, "PNG", optimize=True)
        img.copy().resize((TW, TH), Image.LANCZOS).save(thumb_path, "PNG", optimize=True)
        catalogue.append({
            "id":    slug,
            "label": label,
            "file":  f"{slug}.png",
            "thumb": f"{slug}.thumb.png",
            "w":     W,
            "h":     H,
        })
    cat_path = OUT_DIR / "library.json"
    cat_path.write_text(json.dumps({"version": 1, "items": catalogue}, indent=2),
                         encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT_DIR.iterdir())
    print(f"  wrote {len(WALLPAPERS)} wallpapers + thumbnails + library.json "
          f"({total // 1024} KB total)")


if __name__ == "__main__":
    main()
