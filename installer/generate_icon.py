"""
Build installer/icon.ico from a single Pillow drawing.

We re-use the look of the bridge's tray icon (monitor + 5 RGB pads)
scaled up for installer / Start Menu / file-explorer icons. The .ico
embeds 16, 32, 48, 64, 128, and 256 px renderings so Windows picks the
best size for the context.

Run:  python installer/generate_icon.py
Output: installer/icon.ico
"""

from pathlib import Path

from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0   # scale factor — original art is 64x64

    # Monitor body
    d.rounded_rectangle(
        (6 * s, 8 * s, 58 * s, 42 * s),
        radius=int(3 * s),
        outline=(74, 81, 96, 255),
        width=max(1, int(2 * s)),
        fill=(27, 31, 42, 255),
    )
    # Screen
    d.rectangle((10 * s, 12 * s, 54 * s, 38 * s), fill=(5, 6, 8, 255))
    # Stand
    d.rectangle((26 * s, 46 * s, 38 * s, 49 * s), fill=(74, 81, 96, 255))
    d.rectangle((20 * s, 50 * s, 44 * s, 52 * s), fill=(74, 81, 96, 255))
    # Five RGB pads under the screen edge
    pad_colors = [
        (255, 45, 106),
        (255, 143, 45),
        (255, 233, 45),
        (66, 255, 133),
        (45, 180, 255),
    ]
    centers = [17, 25, 33, 41, 49]
    pad_r = max(1, int(3 * s))
    for cx, color in zip(centers, pad_colors):
        d.ellipse((cx * s - pad_r, 25 * s, cx * s + pad_r, 31 * s), fill=color + (255,))
    return img


def main():
    sizes = [16, 32, 48, 64, 128, 256]
    out = Path(__file__).resolve().parent / "icon.ico"
    base = draw_icon(256)  # render at highest res, .save resamples down
    base.save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {out} ({out.stat().st_size:,} bytes, sizes={sizes})")


if __name__ == "__main__":
    main()
