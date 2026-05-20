"""
Build wallpaper_bridge/wallpaper/workshop_preview.png — the 1920x1080 preview
that ships in every Wallpaper Engine bundle and gets re-used as the Steam
Workshop preview image when uploading.

Same visual vibe as the Lively tile (installer/generate_thumbnail.py) but
scaled for the Workshop browse listing — bigger glow, an actual title +
tagline + a "requires SignalRGB Wallpaper Bridge" footer so subscribers
see the prerequisite before they install.

Run:  python installer/generate_workshop_preview.py
Output: wallpaper_bridge/wallpaper/workshop_preview.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H = 1920, 1080


def linear_gradient(width: int, height: int, top, bottom) -> Image.Image:
    base = Image.new("RGB", (1, height), top)
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        base.putpixel((0, y), (r, g, b))
    return base.resize((width, height))


def draw_workshop_preview() -> Image.Image:
    # Dark backdrop with a subtle diagonal tint shift toward magenta — gives
    # the listing thumb a recognisable signature next to the sea of generic
    # blue Workshop covers.
    bg = linear_gradient(W, H, (12, 16, 28), (32, 14, 46))

    # Big RGB halo at viewport-centre. Drawn at 2x then blurred + downscaled
    # for soft edges; same trick the Lively thumbnail uses.
    halo = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    pad_colors = [
        (255, 45, 106),    # magenta
        (255, 143, 45),    # orange
        (255, 233, 45),    # yellow
        (66, 255, 133),    # green
        (45, 180, 255),    # blue
    ]
    halo_y = int(H * 0.62 * 2)
    halo_spacing = int(W * 0.13 * 2)
    cx0 = (W * 2) // 2 - 2 * halo_spacing
    radius = int(H * 0.40 * 2)
    for i, c in enumerate(pad_colors):
        cx = cx0 + i * halo_spacing
        for alpha, r_mul in [(32, 1.0), (72, 0.55), (160, 0.28)]:
            hd.ellipse(
                (cx - int(radius * r_mul), halo_y - int(radius * r_mul),
                 cx + int(radius * r_mul), halo_y + int(radius * r_mul)),
                fill=(c[0], c[1], c[2], alpha),
            )
    halo = halo.filter(ImageFilter.GaussianBlur(radius=42)).resize((W, H), Image.LANCZOS)
    bg = Image.alpha_composite(bg.convert("RGBA"), halo).convert("RGB")

    d = ImageDraw.Draw(bg)

    # Monitor mock — centred above the halo.
    mon_w, mon_h = int(W * 0.40), int(H * 0.34)
    mon_x = (W - mon_w) // 2
    mon_y = int(H * 0.20)
    d.rounded_rectangle(
        (mon_x, mon_y, mon_x + mon_w, mon_y + mon_h),
        radius=22, outline=(110, 120, 140), width=6, fill=(20, 24, 32),
    )
    pad = 18
    d.rectangle(
        (mon_x + pad, mon_y + pad, mon_x + mon_w - pad, mon_y + mon_h - pad),
        fill=(6, 8, 12),
    )
    # Monitor stand
    stand_w = int(mon_w * 0.18)
    d.rectangle(
        (mon_x + (mon_w - stand_w) // 2, mon_y + mon_h,
         mon_x + (mon_w + stand_w) // 2, mon_y + mon_h + 14),
        fill=(110, 120, 140),
    )
    foot_w = int(mon_w * 0.36)
    d.rectangle(
        (mon_x + (mon_w - foot_w) // 2, mon_y + mon_h + 14,
         mon_x + (mon_w + foot_w) // 2, mon_y + mon_h + 22),
        fill=(110, 120, 140),
    )

    # RGB pads inside the monitor face — same colour set as the halo so the
    # "the monitor is what's producing the glow" reading lands fast.
    pad_count = 5
    pad_r = max(14, mon_h // 14)
    pad_y = mon_y + mon_h - 50
    spacing = (mon_w - 2 * pad) // (pad_count + 1)
    for i, c in enumerate(pad_colors):
        cx = mon_x + pad + spacing * (i + 1)
        d.ellipse((cx - pad_r, pad_y - pad_r, cx + pad_r, pad_y + pad_r), fill=c)

    # Title + tagline + requirement footer
    try:
        font_title   = ImageFont.truetype("segoeuib.ttf", 92)
        font_sub     = ImageFont.truetype("segoeui.ttf",  44)
        font_foot    = ImageFont.truetype("segoeui.ttf",  28)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub   = ImageFont.load_default()
        font_foot  = ImageFont.load_default()

    title = "SignalRGB Wallpaper"
    tw, th = d.textbbox((0, 0), title, font=font_title)[2:]
    d.text(((W - tw) // 2, int(H * 0.05)), title,
           fill=(232, 235, 240), font=font_title)

    sub = "Live RGB glow behind your desktop wallpaper"
    sw, sh = d.textbbox((0, 0), sub, font=font_sub)[2:]
    d.text(((W - sw) // 2, int(H * 0.05) + th + 6), sub,
           fill=(170, 180, 200), font=font_sub)

    # Requirement footer — bottom-strip with a small pill so subscribers
    # spot the bridge-dependency before subscribing.
    foot = "Requires the SignalRGB Wallpaper Bridge from GitHub (Delido/signalrgb-wallpaper)"
    fw, fh = d.textbbox((0, 0), foot, font=font_foot)[2:]
    pad_x, pad_y2 = 26, 12
    box_w = fw + pad_x * 2
    box_h = fh + pad_y2 * 2
    box_x = (W - box_w) // 2
    box_y = H - box_h - 56
    d.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=14, fill=(20, 26, 40), outline=(80, 110, 160), width=2,
    )
    d.text((box_x + pad_x, box_y + pad_y2), foot,
           fill=(200, 210, 230), font=font_foot)

    return bg


def main():
    out = Path(__file__).resolve().parent.parent / "wallpaper_bridge" / "wallpaper" / "workshop_preview.png"
    img = draw_workshop_preview()
    img.save(out, format="PNG", optimize=True)
    print(f"wrote {out} ({out.stat().st_size:,} bytes, {W}x{H})")


if __name__ == "__main__":
    main()
