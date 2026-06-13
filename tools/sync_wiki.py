#!/usr/bin/env python3
"""Mirror docs/*.md into the GitHub Wiki repo.

Single source of truth stays docs/ — this script transforms that markdown
into the flat page layout a GitHub Wiki expects and writes it into a clone
of <repo>.wiki.git. Run by .github/workflows/wiki-sync.yml on every push to
main that touches docs/, or locally for a dry preview:

    python tools/sync_wiki.py <output-dir>

What it does per page:
  * internal  foo.md / foo.md#anchor  ->  foo / foo#anchor (wiki page slugs)
  * index.md links                    ->  Home
  * relative  images/...              ->  absolute raw.githubusercontent URL
    (wiki pages are flat, so relative image paths don't resolve there)

It also generates Home.md (landing) and _Sidebar.md (nav) from the mkdocs
nav, then removes any stale top-level *.md the previous run wrote.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = "Delido/signalrgb-wallpaper"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main/docs/"
PAGES_URL = "https://delido.github.io/signalrgb-wallpaper/"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOCS = ROOT / "docs"
MKDOCS = ROOT / "mkdocs.yml"

# index.md is Material-only (grid cards, :icons:, admonitions) — we generate
# a plain-markdown Home.md instead of mirroring it.
SKIP = {"index.md"}

LINK_RE = re.compile(r"(?<!\!)\]\(([^)\s]+)\)")   # markdown links  ](target)
IMG_RE = re.compile(r"\]\((images/[^)\s]+)\)")     # images   ![alt](images/..)


def _mkdocs_nav() -> list:
    """Read the nav list out of mkdocs.yml, ignoring its !!python/ tags."""

    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_multi_constructor(
        "tag:yaml.org,2002:python/name:", lambda *_: None
    )
    data = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_Loader)
    return data.get("nav", [])


def _slug(md_target: str) -> str:
    """foo.md / foo.md#anchor -> foo / foo#anchor ; index.md -> Home."""
    path, _, anchor = md_target.partition("#")
    page = "Home" if path == "index.md" else path[:-3]  # drop .md
    return page + (f"#{anchor}" if anchor else "")


def _transform(text: str) -> str:
    # images first (more specific), then internal .md links.
    text = IMG_RE.sub(lambda m: f"]({RAW_BASE}{m.group(1)})", text)

    def repl(m: re.Match) -> str:
        target = m.group(1)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        base = target.split("#", 1)[0]
        if base.endswith(".md"):
            return f"]({_slug(target)})"
        return m.group(0)

    return LINK_RE.sub(repl, text)


def _walk(nav, depth=0):
    """Yield (title, page-slug-or-None, depth) entries from the nav tree."""
    for item in nav:
        for title, value in item.items():
            if isinstance(value, str):
                yield title, _slug(value), depth
            else:  # nested section
                yield title, None, depth
                yield from _walk(value, depth + 1)


def _sidebar(nav) -> str:
    lines = ["### [Home](Home)", ""]
    for title, slug, depth in _walk(nav):
        if slug is None:
            lines += ["", f"**{title}**"]
        elif slug == "Home":
            continue
        else:
            lines.append(f"- [{title}]({slug})")
    return "\n".join(lines).strip() + "\n"


def _home(nav) -> str:
    out = [
        "# SignalRGB Desktop Wallpaper",
        "",
        "**Live RGB glow on your desktop, driven by your SignalRGB effect.**",
        "",
        "Multi-monitor · per-screen config · one-click installer · "
        "Lively *and* Wallpaper Engine.",
        "",
        f"![SignalRGB Desktop Wallpaper]({RAW_BASE}images/banner.png)",
        "",
        "---",
        "",
    ]
    for title, slug, depth in _walk(nav):
        if slug is None:
            out += ["", f"### {title}", ""]
        elif slug == "Home":
            continue
        else:
            out.append(f"- [{title}]({slug})")
    out += [
        "",
        "---",
        "",
        f"> 📦 **Downloads:** [latest release]({RELEASES_URL})  ",
        f"> 📖 **Themed docs site:** <{PAGES_URL}>  ",
        "> _This wiki is auto-generated from `docs/` — edit the markdown "
        "there, not here._",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "wiki")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale top-level pages we own (leave .git and any subdirs alone).
    for old in out_dir.glob("*.md"):
        old.unlink()

    nav = _mkdocs_nav()
    written = []

    for md in sorted(DOCS.glob("*.md")):
        if md.name in SKIP:
            continue
        (out_dir / md.name).write_text(
            _transform(md.read_text(encoding="utf-8")), encoding="utf-8"
        )
        written.append(md.name)

    (out_dir / "Home.md").write_text(_home(nav), encoding="utf-8")
    (out_dir / "_Sidebar.md").write_text(_sidebar(nav), encoding="utf-8")

    print(f"Wrote Home.md, _Sidebar.md + {len(written)} pages to {out_dir}")
    for name in written:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
