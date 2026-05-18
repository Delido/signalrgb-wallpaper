"""
Build wallpaper_bridge/wallpaper/thumbnail.png for the Lively tile.

Lively shows each imported wallpaper as a tile in its library. Without a
Thumbnail entry in LivelyInfo.json the tile is plain black — we'd rather
ship a small brand-recognisable image. 480x270 is the standard 16:9 tile
aspect ratio Lively uses; bigger sizes get auto-scaled down anyway.

Run:  python installer/generate_thumbnail.py
Output: wallpaper_bridge/wallpaper/thumbnail.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H = 480, 270


def linear_gradient(width: int, height: int, top, bottom) -> Image.Image:
    img = Image.new("RGB", (width, height), top)
    base = Image.new("RGB", (1, height), top)
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        base.putpixel((0, y), (r, g, b))
    return base.resize((width, height))


def draw_thumbnail() -> Image.Image:
    # Dark vertical gradient backdrop — same vibe as the in-tray dialog.
    bg = linear_gradient(W, H, (15, 20, 32), (28, 12, 40))

    # Soft RGB-glow "halo" centred under the monitor mock, drawn at 3x
    # then downscaled for a fake blur effect that's cheaper than
    # GaussianBlur in PIL.
    halo = Image.new("RGBA", (W * 3, H * 3), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    pad_colors = [
        (255, 45, 106),    # magenta
        (255, 143, 45),    # orange
        (255, 233, 45),    # yellow
        (66, 255, 133),    # green
        (45, 180, 255),    # blue
    ]
    halo_y = int(H * 0.66 * 3)
    halo_spacing = int(W * 0.18 * 3)
    cx0 = (W * 3) // 2 - 2 * halo_spacing
    radius = int(H * 0.32 * 3)
    for i, c in enumerate(pad_colors):
        cx = cx0 + i * halo_spacing
        for a, r_mul in [(28, 1.0), (60, 0.6), (140, 0.3)]:
            hd.ellipse(
                (cx - int(radius * r_mul), halo_y - int(radius * r_mul),
                 cx + int(radius * r_mul), halo_y + int(radius * r_mul)),
                fill=(c[0], c[1], c[2], a),
            )
    halo = halo.filter(ImageFilter.GaussianBlur(radius=18)).resize((W, H), Image.LANCZOS)
    bg = Image.alpha_composite(bg.convert("RGBA"), halo).convert("RGB")

    d = ImageDraw.Draw(bg)

    # Monitor mock — same shape as the tray icon, centred above the halo
    mon_w, mon_h = int(W * 0.42), int(H * 0.36)
    mon_x = (W - mon_w) // 2
    mon_y = int(H * 0.20)
    d.rounded_rectangle(
        (mon_x, mon_y, mon_x + mon_w, mon_y + mon_h),
        radius=8, outline=(80, 90, 110), width=3, fill=(20, 24, 32),
    )
    # Screen interior
    pad = 6
    d.rectangle(
        (mon_x + pad, mon_y + pad, mon_x + mon_w - pad, mon_y + mon_h - pad),
        fill=(6, 8, 12),
    )
    # Stand
    stand_w = int(mon_w * 0.18)
    d.rectangle(
        (mon_x + (mon_w - stand_w) // 2, mon_y + mon_h,
         mon_x + (mon_w + stand_w) // 2, mon_y + mon_h + 4),
        fill=(80, 90, 110),
    )
    foot_w = int(mon_w * 0.36)
    d.rectangle(
        (mon_x + (mon_w - foot_w) // 2, mon_y + mon_h + 4,
         mon_x + (mon_w + foot_w) // 2, mon_y + mon_h + 7),
        fill=(80, 90, 110),
    )

    # RGB pads on the screen face (echoing the tray-icon design)
    pad_count = 5
    pad_r = max(4, mon_h // 14)
    pad_y = mon_y + mon_h - 14
    spacing = (mon_w - 2 * pad) // (pad_count + 1)
    for i, c in enumerate(pad_colors):
        cx = mon_x + pad + spacing * (i + 1)
        d.ellipse((cx - pad_r, pad_y - pad_r, cx + pad_r, pad_y + pad_r), fill=c)

    # Title text
    try:
        font_big   = ImageFont.truetype("segoeuib.ttf", 22)
        font_small = ImageFont.truetype("segoeui.ttf",  13)
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    title = "SignalRGB Glow"
    tw, th = d.textbbox((0, 0), title, font=font_big)[2:]
    d.text(((W - tw) // 2, int(H * 0.06)), title, fill=(232, 235, 240), font=font_big)

    sub = "RGB wallpaper bridge"
    sw, sh = d.textbbox((0, 0), sub, font=font_small)[2:]
    d.text(((W - sw) // 2, int(H * 0.06) + th + 4), sub,
           fill=(160, 168, 184), font=font_small)

    return bg


def main():
    out = Path(__file__).resolve().parent.parent / "wallpaper_bridge" / "wallpaper" / "thumbnail.png"
    img = draw_thumbnail()
    img.save(out, format="PNG", optimize=True)
    print(f"wrote {out} ({out.stat().st_size:,} bytes, {W}x{H})")


if __name__ == "__main__":
    main()
