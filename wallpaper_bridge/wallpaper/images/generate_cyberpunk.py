"""
Procedural Cyberpunk-skyline SVG generator for the SignalRGB Desktop Wallpaper.

Output is a 1920x1080 SVG where:
  - sky (above building tops) is fully transparent
  - building silhouettes are opaque dark blue-black
  - windows and a few billboards are cut out as transparent rectangles
  - antennas/spires sit on top of select buildings as thin opaque lines

Wherever the image is transparent, the glow layer beneath shines through.
Tweak SEED for different layouts. Run:
    python generate_cyberpunk.py [output.svg]
"""

import random
import sys

W, H = 1920, 1080
GROUND_Y = 920
SEED = 7

BG_FILL  = "#06080f"
FG_FILLS = ["#0a0c14", "#0b0d16", "#08090f", "#0c0f18"]
GROUND   = "#040508"
ANTENNA  = "#0a0d18"


def gen_buildings(rng):
    buildings = []
    # background row: short, dark, packed
    x = -10
    while x < W + 10:
        bw = rng.randint(40, 110)
        bh = rng.randint(140, 380)
        buildings.append((x, GROUND_Y - bh, bw, bh, BG_FILL, False))
        x += bw - rng.randint(2, 8)
    # foreground row: tall, lit
    x = -25
    while x < W + 25:
        bw = rng.randint(70, 180)
        bh = rng.randint(250, 720)
        buildings.append((x, GROUND_Y - bh, bw, bh, rng.choice(FG_FILLS), True))
        x += bw - rng.randint(3, 14)
    return buildings


def gen_windows(buildings, rng):
    windows = []
    for bx, by, bw, bh, _, lit in buildings:
        if not lit or bh < 200:
            continue
        ww, wh = 7, 13
        gap_x, gap_y = 11, 17
        cols = max(1, (bw - 12) // (ww + gap_x))
        rows = max(1, (bh - 30) // (wh + gap_y))
        for r in range(rows):
            density = 0.55 if r < rows / 3 else 0.40
            for c in range(cols):
                if rng.random() < density:
                    wx = bx + 6 + c * (ww + gap_x)
                    wy = by + 18 + r * (wh + gap_y)
                    windows.append((wx, wy, ww, wh))
    return windows


def gen_billboards(buildings, rng):
    candidates = [b for b in buildings if b[5] and b[3] > 350]
    if not candidates:
        return []
    picks = rng.sample(candidates, k=min(5, len(candidates)))
    out = []
    for bx, by, bw, bh, _, _ in picks:
        bbw = rng.randint(40, 80)
        bbh = rng.randint(60, 140)
        slack = max(8, bw - bbw - 8)
        bbx = bx + rng.randint(8, slack)
        bby = by + rng.randint(40, bh - bbh - 40)
        out.append((bbx, bby, bbw, bbh))
    return out


def gen_antennas(buildings, rng):
    tall = [b for b in buildings if b[5] and b[3] > 400]
    if not tall:
        return []
    picks = rng.sample(tall, k=min(8, len(tall)))
    out = []
    for bx, by, bw, bh, _, _ in picks:
        ax = bx + bw // 2 + rng.randint(-10, 10)
        height = rng.randint(40, 120)
        out.append((ax, by - height, ax, by))
    return out


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "cyberpunk_skyline.svg"
    rng = random.Random(SEED)

    buildings = gen_buildings(rng)
    windows   = gen_windows(buildings, rng)
    billboards = gen_billboards(buildings, rng)
    antennas  = gen_antennas(buildings, rng)

    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">')
    parts.append('<defs><mask id="m">')
    parts.append('<rect width="1920" height="1080" fill="white"/>')
    for wx, wy, ww, wh in windows:
        parts.append(f'<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" fill="black"/>')
    for bx, by, bw, bh in billboards:
        parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="black"/>')
    parts.append('</mask></defs>')

    parts.append('<g mask="url(#m)">')
    for bx, by, bw, bh, fill, _ in buildings:
        parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="{fill}"/>')
    parts.append(f'<rect x="0" y="{GROUND_Y}" width="{W}" height="{H - GROUND_Y}" fill="{GROUND}"/>')
    parts.append('</g>')

    for x1, y1, x2, y2 in antennas:
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{ANTENNA}" stroke-width="2"/>')

    parts.append('</svg>')
    svg = '\n'.join(parts)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {out_path}: {len(svg)} bytes, {len(buildings)} buildings, {len(windows)} windows, {len(billboards)} billboards, {len(antennas)} antennas")


if __name__ == "__main__":
    main()
