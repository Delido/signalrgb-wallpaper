"""
Build docs/images/banner.png for the README hero.

Same visual language as the Lively tile thumbnail (RGB-monitor mark on
a dark gradient with a soft rainbow halo) but in 1280x320 banner form
and with the project name + tagline rendered as text. GitHub renders
README images at full width so this size is roughly the natural
breakpoint before they start downscaling.

Run:  python installer/generate_banner.py
Output: docs/images/banner.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H = 1280, 320


def linear_gradient(width: int, height: int, top, bottom) -> Image.Image:
    base = Image.new("RGB", (1, height), top)
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        base.putpixel((0, y), (r, g, b))
    return base.resize((width, height))


def _try_font(family_candidates, size):
    for name in family_candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_banner() -> Image.Image:
    bg = linear_gradient(W, H, (12, 18, 30), (40, 14, 56))

    # Soft RGB halo across the bottom — same five brand colours we use
    # for the monitor pads. Drawn at 3x then downscaled for a cheap blur.
    halo = Image.new("RGBA", (W * 3, H * 3), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    pad_colors = [
        (255, 45, 106),   # magenta
        (255, 143, 45),   # orange
        (255, 233, 45),   # yellow
        (66, 255, 133),   # green
        (45, 180, 255),   # blue
    ]
    halo_y = int(H * 0.85 * 3)
    halo_spacing = int(W * 0.16 * 3)
    cx0 = (W * 3) // 2 - 2 * halo_spacing
    radius = int(H * 0.85 * 3)
    for i, c in enumerate(pad_colors):
        cx = cx0 + i * halo_spacing
        for a, r_mul in [(22, 1.0), (45, 0.55), (100, 0.25)]:
            hd.ellipse(
                (cx - int(radius * r_mul), halo_y - int(radius * r_mul),
                 cx + int(radius * r_mul), halo_y + int(radius * r_mul)),
                fill=(c[0], c[1], c[2], a),
            )
    halo = halo.filter(ImageFilter.GaussianBlur(radius=28)).resize((W, H), Image.LANCZOS)
    bg = Image.alpha_composite(bg.convert("RGBA"), halo).convert("RGB")

    d = ImageDraw.Draw(bg)

    # Monitor mock on the left
    mon_w, mon_h = 220, 150
    mon_x = 80
    mon_y = (H - mon_h) // 2 - 18
    d.rounded_rectangle(
        (mon_x, mon_y, mon_x + mon_w, mon_y + mon_h),
        radius=10, outline=(80, 90, 110), width=3, fill=(20, 24, 32),
    )
    pad = 8
    d.rectangle(
        (mon_x + pad, mon_y + pad, mon_x + mon_w - pad, mon_y + mon_h - pad),
        fill=(5, 6, 10),
    )
    stand_w = 42
    d.rectangle(
        (mon_x + (mon_w - stand_w) // 2, mon_y + mon_h,
         mon_x + (mon_w + stand_w) // 2, mon_y + mon_h + 8),
        fill=(80, 90, 110),
    )
    foot_w = 96
    d.rectangle(
        (mon_x + (mon_w - foot_w) // 2, mon_y + mon_h + 8,
         mon_x + (mon_w + foot_w) // 2, mon_y + mon_h + 12),
        fill=(80, 90, 110),
    )
    # RGB pads inside the monitor screen — bigger here than on the tile
    pad_r = 11
    pad_y = mon_y + mon_h - 28
    spacing = (mon_w - 2 * pad) // 6
    for i, c in enumerate(pad_colors):
        cx = mon_x + pad + spacing * (i + 1)
        d.ellipse((cx - pad_r, pad_y - pad_r, cx + pad_r, pad_y + pad_r), fill=c)

    # Text — title + tagline. Segoe UI is on every Windows install.
    font_title = _try_font(["segoeuib.ttf", "arialbd.ttf"], 56)
    font_tag   = _try_font(["segoeui.ttf",  "arial.ttf"],   22)
    font_meta  = _try_font(["segoeui.ttf",  "arial.ttf"],   16)

    text_x = mon_x + mon_w + 56
    d.text((text_x, 80),  "SignalRGB Glow Wallpaper",
           fill=(238, 240, 246), font=font_title)
    d.text((text_x, 156), "Live RGB glow on your desktop, driven by your SignalRGB effect.",
           fill=(180, 188, 204), font=font_tag)
    d.text((text_x, 200), "Multi-monitor · in-browser builder · one-click installer",
           fill=(120, 134, 158), font=font_meta)

    return bg


def main():
    out = Path(__file__).resolve().parent.parent / "docs" / "images" / "banner.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = draw_banner()
    img.save(out, format="PNG", optimize=True)
    print(f"wrote {out} ({out.stat().st_size:,} bytes, {W}x{H})")


if __name__ == "__main__":
    main()
