"""
Batch-generate the bundled library wallpapers via a local Gradio
SDXL-Lightning instance, replacing the previous Bing/DALL-E sources
with permissively-licensed outputs (CreativeML Open RAIL++-M — output
clause IV/V allows free redistribution for non-prohibited use cases).

Assumed running:
  python C:\\Users\\smend\\app_signalrgb.py
  → Gradio UI on http://127.0.0.1:7860, exposing api_name="generate"
     with inputs (prompt, target_size, make_transparent).

Usage:
  python tools/generate_via_gradio.py            # all slugs
  python tools/generate_via_gradio.py aurora     # only matching slugs
  python tools/generate_via_gradio.py --list     # print slug → prompt

Output:
  tools/starter-images-in/<slug>.png   (1920x1080)
  tools/starter-images-in/<slug>.meta  (JSON with label override)

Then run tools/process_starter_images.py — that pipeline takes care
of the saliency cut, WebP conversion, and library.json upsert.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "starter-images-in"

GRADIO_URL = "http://127.0.0.1:7860"

# Style A: themed per slug — each prompt leans into the slug's own
# semantics (aurora, cyberpunk neon, deep-sea bioluminescence,
# mushroom forest, etc.) rather than a single unified look. SDXL-
# Lightning is a 4-step model; long over-stuffed prompts dilute it,
# so each entry stays focused on subject + mood + lighting and lets
# the model fill in detail.
PROMPTS: dict[str, tuple[str, str]] = {
    # slug → (label, prompt)
    "aurora-curtain":
        ("Aurora Curtain",
         "majestic aurora borealis dancing across the night sky, vivid green "
         "and violet curtains of light, distant mountain silhouette, starry "
         "background, ultrawide cinematic landscape"),
    "aurora-horizon":
        ("Aurora Horizon",
         "northern lights rippling above a calm dark horizon, soft teal and "
         "magenta bands, reflection on still water, photo-real, cinematic"),
    "aurora-pines":
        ("Aurora Pines",
         "aurora borealis above a snowy pine forest, vivid green and pink "
         "ribbons of light, moonlit clearing, ultrawide composition"),
    "aurora-sky":
        ("Aurora Sky",
         "wide aurora borealis sky, electric green and violet glow, deep "
         "starfield, faint mountain ridge low on the horizon"),
    "bioluminescent-grove":
        ("Bioluminescent Grove",
         "magical bioluminescent forest grove at night, glowing cyan plants "
         "and turquoise mushrooms, mist between trees, fantasy concept art"),
    "cyan-cyberpunk-highway":
        ("Cyan Cyberpunk Highway",
         "cyberpunk highway at night, cyan light trails of speeding cars, "
         "futuristic neon billboards, wet asphalt reflections, cinematic"),
    "cyan-skyline":
        ("Cyan Skyline",
         "futuristic city skyline glowing in deep cyan, towering glass "
         "skyscrapers, foggy night sky, neon accents, cinematic wide shot"),
    "cyberpunk-bridge-vista":
        ("Cyberpunk Bridge Vista",
         "vast cyberpunk megacity bridge at night, glowing magenta and cyan "
         "lights, holographic billboards, foggy atmosphere, ultrawide vista"),
    "cyberpunk-holo-street":
        ("Cyberpunk Holo Street",
         "rainy cyberpunk street with floating holographic advertisements, "
         "neon pink and blue signage, reflective wet pavement, atmospheric"),
    "cyberpunk-twin-towers":
        ("Cyberpunk Twin Towers",
         "two enormous cyberpunk skyscrapers towering above a neon-lit city, "
         "deep pink and purple atmosphere, low-angle hero shot, cinematic"),
    "deep-sea-jellies":
        ("Deep Sea Jellies",
         "deep ocean scene with glowing translucent jellyfish, bioluminescent "
         "tendrils in cyan and magenta, particles drifting in dark water, "
         "macro detail, cinematic"),
    "foggy-neon-street":
        ("Foggy Neon Street",
         "narrow city alley shrouded in dense fog, glowing neon shop signs in "
         "pink and teal, wet cobblestones, lonely lantern, moody atmosphere"),
    "magenta-alley":
        ("Magenta Alley",
         "narrow cyberpunk alley bathed in deep magenta neon, reflective "
         "puddles, hanging signs, sci-fi noir, cinematic wide shot"),
    "magenta-cyberpunk":
        ("Magenta Cyberpunk",
         "cyberpunk cityscape drenched in vivid magenta light, towering "
         "buildings, glowing windows, holographic projections, ultrawide"),
    "mushroom-forest":
        ("Mushroom Forest",
         "enchanted forest with giant glowing mushrooms, soft purple and "
         "teal light, mist between roots, fairy-tale concept art"),
    "neon-backstreet":
        ("Neon Backstreet",
         "narrow back street in a neon-lit district, vibrant signs in "
         "Chinese and Japanese script, rain-soaked pavement, cinematic"),
    "neon-boulevard":
        ("Neon Boulevard",
         "wide neon-lit city boulevard at night, twin rows of glowing signs, "
         "long perspective vanishing point, vibrant pink and cyan, cinematic"),
    "neon-magenta-alley":
        ("Neon Magenta Alley",
         "intimate cyberpunk alley flooded in magenta and violet neon, "
         "overhead signs, steam rising, wet floor reflections, atmospheric"),
    "neon-storefront":
        ("Neon Storefront",
         "futuristic storefront wall covered in dense neon signage, mix of "
         "pink and cyan, late-night street ambience, cinematic wide shot"),
    "neon-street-pink":
        ("Neon Street Pink",
         "cyberpunk street drenched in hot pink neon, glowing kanji signs, "
         "rain reflections, distant skyline, cinematic"),
    "night-city-vista":
        ("Night City Vista",
         "sprawling futuristic night city seen from a rooftop, vivid neon "
         "grid below, towering skyscrapers, starlit sky, ultrawide vista"),
    "plasma-web":
        ("Plasma Web",
         "abstract glowing plasma web, electric arcs of magenta and cyan "
         "energy on a dark void, sci-fi background"),
    "quantum-wave":
        ("Quantum Wave",
         "abstract quantum waveform, glowing concentric ripples of cyan and "
         "violet on a deep black canvas, particles, scientific aesthetic"),
    "rgb-abstract":
        ("RGB Abstract",
         "abstract RGB light streaks, ribbons of pure red green and blue "
         "weaving through a dark gradient, soft glow, minimal background"),
    "rgb-curve":
        ("RGB Curve",
         "sweeping RGB light curve, glowing gradient ribbon of red green "
         "and blue, smooth bokeh background, minimal composition"),
    "rgb-setup-arch":
        ("RGB Setup Arch",
         "futuristic gaming setup viewed from behind a monitor arch, RGB "
         "underglow on a curved desk, ambient pink and cyan lighting, "
         "cinematic"),
    "rgb-studio":
        ("RGB Studio",
         "modern creator studio at night, RGB ambient lighting on shelves "
         "and walls, soft purple and teal accents, atmospheric depth"),
    "spaceship-bridge":
        ("Spaceship Bridge",
         "command bridge of a futuristic spaceship, glowing holographic "
         "displays, cyan and orange ambient light, sci-fi cinematic shot"),
    "stellar-burst":
        ("Stellar Burst",
         "stellar nebula bursting with vivid magenta and cyan stars, deep "
         "space scene, soft volumetric glow, hubble-style composition"),
    "synthwave-horizon":
        ("Synthwave Horizon",
         "classic synthwave horizon, grid floor receding into a giant "
         "magenta sun, distant silhouette mountains, retro 80s aesthetic"),
    "synthwave-mountains":
        ("Synthwave Mountains",
         "retro synthwave landscape with neon outlined mountains, gradient "
         "magenta to cyan sky, sparkling stars, glowing grid foreground"),
    "synthwave-sun":
        ("Synthwave Sun",
         "huge horizontal-striped synthwave sun rising on the horizon, "
         "vivid magenta and orange gradient sky, glowing neon grid floor "
         "stretching to vanishing point, retro 80s vibe, no people, no "
         "vehicles, minimal foreground, wide cinematic landscape"),
    "tokyo-bridge-vista":
        ("Tokyo Bridge Vista",
         "Tokyo Rainbow Bridge style night scene, glowing teal and pink "
         "lights reflecting on calm bay, distant skyline, cinematic"),
    "tokyo-neon-alley":
        ("Tokyo Neon Alley",
         "narrow Tokyo alley packed with vertical neon signs in Japanese "
         "script, glowing pink and blue, rainy pavement, cinematic"),
    "tokyo-vista":
        ("Tokyo Vista",
         "sweeping nighttime view of futuristic Tokyo, towering skyline, "
         "dense neon, distant Mount Fuji silhouette, cinematic ultrawide"),
    "underwater-jellies":
        ("Underwater Jellies",
         "underwater scene with floating jellyfish glowing in vivid cyan "
         "and pink, beams of caustic light from above, dreamy atmosphere"),
    "wet-neon-alley":
        ("Wet Neon Alley",
         "rain-soaked cyberpunk alley at night, glossy reflections of "
         "magenta and cyan neon signs, steam rising, cinematic noir"),
    "wet-neon-street":
        ("Wet Neon Street",
         "wet city street after rain, vivid neon reflections, pink and "
         "blue light pools on glossy asphalt, cinematic atmospheric"),
}


def call_gradio(prompt: str) -> Path:
    """Hit the local Gradio /generate endpoint, return the temp PNG path."""
    try:
        from gradio_client import Client
    except ImportError:
        print("Missing gradio_client. Install it with:")
        print("  pip install gradio_client")
        sys.exit(1)

    client = Client(GRADIO_URL)
    result = client.predict(
        prompt,                       # prompt
        "Full HD (1920x1080)",        # target_size
        False,                        # make_transparent — saliency is later
        api_name="/generate",
    )
    # Gradio returns either a path or a dict {"path": "..."}; handle both.
    if isinstance(result, dict):
        path = result.get("path") or result.get("name") or ""
    else:
        path = result
    p = Path(str(path))
    if not p.exists():
        raise RuntimeError(f"gradio returned non-existent path: {p}")
    return p


def write_meta(slug: str, label: str) -> None:
    meta = OUT_DIR / f"{slug}.meta"
    meta.write_text(json.dumps({
        "slug": slug,
        "label": label,
        "source": "SDXL-Lightning (CreativeML Open RAIL++-M)",
    }, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", default="",
                    help="substring filter on slug (empty = all)")
    ap.add_argument("--list", action="store_true",
                    help="print slug → prompt and exit")
    ap.add_argument("--force", action="store_true",
                    help="re-generate even if output already exists")
    args = ap.parse_args()

    if args.list:
        for slug, (label, prompt) in PROMPTS.items():
            print(f"{slug:32s}  {prompt}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sel = [s for s in PROMPTS if not args.filter or args.filter in s]
    if not sel:
        print(f"no slug matches filter: {args.filter}")
        return 2

    print(f"generating {len(sel)} images via {GRADIO_URL}")
    total_start = time.monotonic()
    ok, skipped, failed = 0, 0, 0
    for i, slug in enumerate(sel, 1):
        label, prompt = PROMPTS[slug]
        dst = OUT_DIR / f"{slug}.png"
        if dst.exists() and not args.force:
            print(f"  [{i:2d}/{len(sel)}] {slug:32s}  SKIP (exists)")
            skipped += 1
            continue
        t0 = time.monotonic()
        try:
            tmp = call_gradio(prompt)
            shutil.copy2(tmp, dst)
            write_meta(slug, label)
            dt = time.monotonic() - t0
            print(f"  [{i:2d}/{len(sel)}] {slug:32s}  OK  ({dt:4.1f}s)")
            ok += 1
        except Exception as e:
            print(f"  [{i:2d}/{len(sel)}] {slug:32s}  FAIL  {e}")
            failed += 1

    dt_total = time.monotonic() - total_start
    print()
    print(f"done in {dt_total:.1f}s: {ok} ok, {skipped} skipped, {failed} failed")
    print(f"output: {OUT_DIR}")
    print("next: python tools/process_starter_images.py")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
