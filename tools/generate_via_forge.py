"""
Batch-generate the bundled library wallpapers via Forge WebUI's
sdapi (port 7860). Targets Juggernaut XL v9 — CreativeML Open
RAIL++-M, Output unencumbered. Saves to tools/starter-images-in/
ready for process_starter_images.py.

Usage:
  # Run Forge first (run.bat with --api in COMMANDLINE_ARGS), then:
  python tools/generate_via_forge.py            # all slugs
  python tools/generate_via_forge.py aurora     # filter
  python tools/generate_via_forge.py --list

Notes:
  * Native gen at 1920x1088 with Juggernaut (best quality / runtime
    sweet spot — ~22 s on a 4070 Ti). The .meta sidecar tells
    process_starter_images.py how to label the slug.
  * No hires.fix call — Forge's API for that path is broken in
    the current build (returns "argument of type 'NoneType' is
    not iterable"). The 4K variant comes from a PIL Lanczos pass
    in process_starter_images.py.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import urllib.request

# Reuse the slug → (label, prompt) table from generate_via_gradio.py
# so a re-run with either backend produces the same slug set.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_via_gradio import PROMPTS as _GRADIO_PROMPTS  # noqa: E402

PROMPTS = _GRADIO_PROMPTS

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "starter-images-in"

FORGE_URL = "http://127.0.0.1:7860"
TARGET_MODEL = "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"

# Negative prompt is the same for every slug — generic safety net
# against the usual SDXL failure modes. Keeping it short matters more
# than enumerating every quality term.
NEGATIVE = ("blurry, low quality, distorted, watermark, text, signature, "
            "cartoon, anime, oversaturated, ugly, deformed, jpeg artifacts, "
            "airplane, aircraft, jet, helicopter, drone, ufo")

# Native size — Juggernaut sweet spot. 1920x1088 is a hair above
# 1920x1080 because SDXL prefers multiples of 64. We crop down to
# 1920x1080 (or upscale to 3840x2160) in process_starter_images.py.
WIDTH  = 1920
HEIGHT = 1088
STEPS  = 32
CFG    = 6.5
SAMPLER = "DPM++ 2M"


def _post(path: str, payload: dict, timeout: float = 600.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        FORGE_URL + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str, timeout: float = 30.0) -> dict | list:
    req = urllib.request.Request(FORGE_URL + path)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_model(name: str) -> None:
    """Switch the active SD checkpoint if Forge isn't already on it."""
    opts = _get("/sdapi/v1/options")
    cur = opts.get("sd_model_checkpoint", "")
    if name in cur:
        print(f"  model already active: {cur}")
        return
    print(f"  switching model: {cur or '(none)'}  ->  {name}")
    _post("/sdapi/v1/options", {"sd_model_checkpoint": name}, timeout=180)
    # Forge schedules the load on the next txt2img call; nothing else
    # to do here. Verify it stuck.
    opts2 = _get("/sdapi/v1/options")
    print(f"  active now: {opts2.get('sd_model_checkpoint', '?')}")


def txt2img(prompt: str) -> bytes:
    payload = {
        "prompt": prompt,
        "negative_prompt": NEGATIVE,
        "steps": STEPS,
        "width":  WIDTH,
        "height": HEIGHT,
        "cfg_scale": CFG,
        "sampler_name": SAMPLER,
        "seed": -1,
    }
    resp = _post("/sdapi/v1/txt2img", payload, timeout=300)
    imgs = resp.get("images") or []
    if not imgs:
        raise RuntimeError("Forge returned no images")
    return base64.b64decode(imgs[0])


def write_meta(slug: str, label: str) -> None:
    # YAML-ish line format — what process_starter_images.read_meta_sidecar
    # expects. JSON would silently fall through to slug/label defaults.
    meta = OUT_DIR / f"{slug}.meta"
    meta.write_text(
        f"slug: {slug}\n"
        f"label: {label}\n"
        f"# source: Juggernaut XL v9 (CreativeML Open RAIL++-M)\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", default="",
                    help="substring filter on slug (empty = all)")
    ap.add_argument("--list", action="store_true",
                    help="print slug list and exit")
    ap.add_argument("--force", action="store_true",
                    help="re-generate even if output exists")
    args = ap.parse_args()

    if args.list:
        for slug, (label, prompt) in PROMPTS.items():
            print(f"{slug:32s}  {prompt[:80]}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sel = [s for s in PROMPTS if not args.filter or args.filter in s]
    if not sel:
        print(f"no slug matches filter: {args.filter}")
        return 2

    print(f"target: Juggernaut XL v9 via {FORGE_URL}")
    try:
        ensure_model(TARGET_MODEL)
    except Exception as e:
        print(f"model check failed: {e}")
        return 1

    print(f"\ngenerating {len(sel)} image(s) at {WIDTH}x{HEIGHT}, "
          f"{STEPS} steps {SAMPLER} cfg {CFG}")
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
            png = txt2img(prompt)
            dst.write_bytes(png)
            write_meta(slug, label)
            dt = time.monotonic() - t0
            print(f"  [{i:2d}/{len(sel)}] {slug:32s}  OK  ({dt:4.1f}s, "
                  f"{len(png) // 1024} KB)")
            ok += 1
        except Exception as e:
            print(f"  [{i:2d}/{len(sel)}] {slug:32s}  FAIL  {e}")
            failed += 1

    dt = time.monotonic() - total_start
    print()
    print(f"done in {dt:.1f}s: {ok} ok, {skipped} skipped, {failed} failed")
    print(f"output: {OUT_DIR}")
    print("next: python tools/process_starter_images.py")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
