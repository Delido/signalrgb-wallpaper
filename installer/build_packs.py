"""
Build downloadable Wallpaper-Pack ZIPs from installer/packs/<theme>/
sources. Each pack ZIP contains every WebP (main + thumb + 4K) for
its theme plus a `manifest.json` that the bridge consumes to build
catalogue entries after extraction.

Output layout:
  installer_out/packs/
    cyberpunk-pack-v1.zip
    aurora-nature-pack-v1.zip
    synthwave-abstract-pack-v1.zip

Pack ZIPs are uploaded as GitHub release assets; the discovery
manifest at docs/library-packs.json points at the release download
URLs. See generate_library.py for the parallel tag-derivation rules
used at install time.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "packs"
OUT = HERE.parent / "installer_out" / "packs"
PACK_VERSION = 1
WALLPAPER_W = 1920
WALLPAPER_H = 1080

# Pack metadata: id -> (label EN, label DE, description). v1.7.5
# wave 2 uses one pack per source category (13 packs) instead of
# bundled themes — discoverability over consolidation.
PACK_META = {
    "aurora":      ("Aurora",     "Aurora",
                    "Northern lights over mountains, lakes and snow — atmospheric sky wallpapers."),
    "blockbuster": ("Blockbuster", "Blockbuster",
                    "Cinematic blockbuster-style hero scenes."),
    "crystal":     ("Crystal",    "Kristall",
                    "Crystalline structures, gem facets and mineral light refractions."),
    "cyberpunk":   ("Cyberpunk",  "Cyberpunk",
                    "Neon megacities, holographic streets and rain-soaked alleys."),
    "energy":      ("Energy",     "Energie",
                    "Electric arcs, plasma fields and high-voltage abstract glow."),
    "film":        ("Film",       "Film",
                    "Cinematic stills and atmospheric movie-style compositions."),
    "fireworks":   ("Fireworks",  "Feuerwerk",
                    "Burst, sparkle and trail patterns of pyrotechnic light."),
    "forest":      ("Forest",     "Wald",
                    "Mystical woodlands, glowing canopies and atmospheric forest light."),
    "magic":       ("Magic",      "Magie",
                    "Fantasy arcane glow, magical runes and mystical light fields."),
    "space":       ("Space",      "Weltraum",
                    "Deep-space nebulae, stellar bursts and distant cosmic vistas."),
    "synthwave":   ("Synthwave",  "Synthwave",
                    "Retro 80s grid sunsets, neon mountains and chrome horizons."),
    "underwater":  ("Underwater", "Unterwasser",
                    "Bioluminescent deep-sea creatures, kelp forests and abyssal light."),
    "videospiele": ("Video Games", "Videospiele",
                    "Iconic game-style scenes — fantasy castles, sci-fi vistas, dungeons."),
}

# v1.7.5: license + generator metadata travels with each pack so the
# Configurator can surface "Generated with X (License Y)" in the
# pack browser. All current packs share the same chain — Juggernaut
# XL v9 image gen + Phips' 4xNomos8kDAT for the 4K upscale.
PACK_LICENSE_META = {
    "license":            "CreativeML Open RAIL-M",
    "license_url":        "https://huggingface.co/spaces/CompVis/stable-diffusion-license",
    "commercial_use":     True,
    "redistribution":     "MIT-compatible",
    "generators": [
        {
            "name":    "Juggernaut XL v9 (RunDiffusion Photo v2)",
            "role":    "Image generation",
            "license": "CreativeML Open RAIL-M (+ RunDiffusion addendum)",
            "url":     "https://civitai.com/models/133005/juggernaut-xl",
        },
        {
            "name":    "4xNomos8kDAT by Philip Hofmann (Phips)",
            "role":    "4K upscale",
            "license": "CC-BY-4.0",
            "url":     "https://huggingface.co/Phips/4xNomos8kDAT",
        },
    ],
}

# Reuse generate_library.py's tag derivation rules for consistency.
sys.path.insert(0, str(HERE))
from generate_library import _tags_for_slug  # noqa: E402


def _label_for_slug(slug: str) -> str:
    parts = re.split(r"[-_]+", slug)
    return " ".join(p[:1].upper() + p[1:] for p in parts if p)


def build_pack(pack_id: str, src_dir: Path) -> dict:
    if not src_dir.is_dir():
        raise FileNotFoundError(src_dir)
    label_en, label_de, desc = PACK_META.get(
        pack_id, (_label_for_slug(pack_id), _label_for_slug(pack_id), ""))

    # Enumerate slugs (main files only — thumbs + 4k tagged along).
    mains = sorted(p for p in src_dir.glob("*.webp")
                   if not p.stem.endswith(".thumb")
                   and not p.stem.endswith(".4k"))
    if not mains:
        print(f"  [{pack_id}] no images — skipping")
        return {}

    items = []
    for main in mains:
        slug = main.stem
        thumb = src_dir / f"{slug}.thumb.webp"
        file4k = src_dir / f"{slug}.4k.webp"
        entry = {
            "id":       slug,
            "label":    _label_for_slug(slug),
            "file":     main.name,
            "w":        WALLPAPER_W,
            "h":        WALLPAPER_H,
            "category": "background",
            "tags":     _tags_for_slug(slug),
        }
        if thumb.exists():
            entry["thumb"] = thumb.name
        if file4k.exists():
            entry["file4k"] = file4k.name
        items.append(entry)

    manifest = {
        "schema": 1,
        "pack_id":      pack_id,
        "pack_version": PACK_VERSION,
        "label":        {"en": label_en, "de": label_de},
        "description":  desc,
        "image_count":  len(items),
        "items":        items,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    zip_path = OUT / f"{pack_id}-pack-v{PACK_VERSION}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                          compresslevel=9) as zf:
        # WebPs are already compressed; zip-deflate buys ~0 % but
        # the embedded JSON does compress, so leave ZIP_DEFLATED on.
        for main in mains:
            zf.write(main, main.name)
            for sib_name in (f"{main.stem}.thumb.webp",
                              f"{main.stem}.4k.webp"):
                sib = src_dir / sib_name
                if sib.exists():
                    zf.write(sib, sib.name)
        zf.writestr("manifest.json",
                    json.dumps(manifest, indent=2, ensure_ascii=False))

    # v1.7.5 wave 2: copy the first 4 thumb WebPs out as flat preview
    # assets so the Configurator can show real thumbnails on
    # not-yet-installed packs. Names are flat + pack-prefixed because
    # they all share one release-assets bucket.
    preview_dir = OUT / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_assets: list[str] = []
    for i, main in enumerate(mains[:4]):
        thumb_src = src_dir / f"{main.stem}.thumb.webp"
        if not thumb_src.exists():
            continue
        asset_name = f"{pack_id}-preview-{i}.webp"
        (preview_dir / asset_name).write_bytes(thumb_src.read_bytes())
        preview_assets.append(asset_name)

    size = zip_path.stat().st_size
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    print(f"  [{pack_id}] {len(items)} images, {size // 1024} KB, sha256={sha[:12]}…")
    return {
        "id":           pack_id,
        "version":      PACK_VERSION,
        "label":        {"en": label_en, "de": label_de},
        "description":  desc,
        "image_count":  len(items),
        "size_bytes":   size,
        "sha256":       sha,
        "filename":     zip_path.name,
        "preview_thumbs": [it.get("thumb") or it["file"]
                           for it in items[:4]],
        # v1.7.5 wave 2: absolute URLs for the preview WebPs we just
        # extracted. The bridge passes these through to the
        # Configurator, which loads them directly from GitHub release
        # assets — no install-step required.
        "preview_urls":   [RELEASE_BASE + a for a in preview_assets],
        # v1.7.5: slug list so the bridge can detect "installed"
        # state from file presence alone — handles upgrade-from-
        # pre-pack-split installs where the WebPs are already in
        # library_dir but no marker file marks them as belonging
        # to a pack.
        "slugs":        [it["id"] for it in items],
        # v1.7.5 wave 2: license metadata travels per pack so the
        # Configurator can surface generator + license info in the
        # pack browser without a separate lookup.
        **PACK_LICENSE_META,
    }


DISCOVERY_MANIFEST = HERE.parent / "docs" / "library-packs.json"
# Where the bridge expects to find downloadable packs. Each pack's
# `url` field is built from this base + the pack ZIP filename. The
# v1.7.5-beta release is the carrier release; future packs can ship
# in their own dedicated `library-packs-vN` releases without bumping
# the app.
RELEASE_TAG = "v1.7.5-beta"
RELEASE_BASE = (
    "https://github.com/Delido/signalrgb-wallpaper/releases/download/"
    + RELEASE_TAG + "/"
)


def main() -> int:
    if not SRC.exists():
        print(f"no source dir: {SRC}", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"building packs from {SRC}/ -> {OUT}/\n")
    catalogue = []
    for pack_dir in sorted(SRC.iterdir()):
        if not pack_dir.is_dir():
            continue
        meta = build_pack(pack_dir.name, pack_dir)
        if meta:
            meta["url"] = RELEASE_BASE + meta["filename"]
            catalogue.append(meta)

    # Discovery manifest the bridge fetches from raw.githubusercontent.com.
    # Keep it in docs/ so it's served straight off the main branch
    # via the well-known raw URL pattern.
    DISCOVERY_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_MANIFEST.write_text(
        json.dumps({
            "schema":      1,
            "min_app":     "1.7.5-beta",
            "packs":       catalogue,
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print()
    print(f"built {len(catalogue)} pack(s)")
    print(f"discovery manifest: {DISCOVERY_MANIFEST.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
