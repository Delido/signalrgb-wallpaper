"""Prepare a release: bump APP_VERSION, add the RELEASE_NOTES entry and the
CHANGELOG section from one JSON file, then check the result parses.

    python tools/release_prep.py notes.json            # write
    python tools/release_prep.py notes.json --dry-run  # show what it would do

notes.json:
    {
      "version": "2.7.0-beta.9",
      "wallpaper_version": "2.4.23",          # optional; only if wallpaper/ changed
      "body_en": "**Fixed: ...**\\n\\nMore text.",
      "body_de": "**Behoben: ...**\\n\\nMehr Text.",
      "changelog": "### Fixed — ...\\n\\n- ..."  # Markdown, without the version heading
    }

Why a script: writing the RELEASE_NOTES entry by hand through a shell
heredoc turned "\\n" into real line breaks inside Python string literals
twice (v2.6.1-beta.1, v2.7.0-beta.1) and only the release run's test step
caught it. Here the bodies are emitted with repr-style escaping, so the
literal is always valid, and the module is parsed before anything is
written.
"""
import argparse
import ast
import datetime
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = REPO / "wallpaper_bridge" / "bridge.py"
CHANGELOG = REPO / "CHANGELOG.md"


def py_str_lines(text: str, indent: str) -> str:
    """Split a body into adjacent string literals, one per output line,
    each escaped so it is always a valid single-line literal."""
    parts = re.findall(r".{1,60}(?:\s+|$)|.{1,60}", text, re.S) or [""]
    out = []
    for p in parts:
        lit = json.dumps(p, ensure_ascii=True)      # escapes \n, quotes, non-ASCII
        out.append(indent + lit)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("notes")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    n = json.loads(pathlib.Path(a.notes).read_text(encoding="utf-8"))
    ver = n["version"]

    src = BRIDGE.read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION = "([^"]+)"$', src, re.M)
    old = m.group(1)
    if old == ver:
        sys.exit(f"APP_VERSION is already {ver}")
    if f'    "{ver}": {{' in src:
        sys.exit(f"RELEASE_NOTES already has {ver}")
    src = src.replace(f'APP_VERSION = "{old}"', f'APP_VERSION = "{ver}"', 1)
    if n.get("wallpaper_version"):
        src, k = re.subn(r'^WALLPAPER_VERSION = "[^"]+"$',
                         f'WALLPAPER_VERSION = "{n["wallpaper_version"]}"', src, count=1, flags=re.M)
        if not k:
            sys.exit("WALLPAPER_VERSION not found")
    ind = " " * 12
    title_en = json.dumps("What's new in v" + ver)
    title_de = json.dumps("Was ist neu in v" + ver)
    entry = (
        f'RELEASE_NOTES = {{\n'
        f'    "{ver}": {{\n'
        f'        "title_en": {title_en},\n'
        f'        "title_de": {title_de},\n'
        f'        "body_en": (\n{py_str_lines(n["body_en"], ind)}\n        ),\n'
        f'        "body_de": (\n{py_str_lines(n["body_de"], ind)}\n        ),\n'
        f'    }},\n'
    )
    if src.count("RELEASE_NOTES = {\n") != 1:
        sys.exit("RELEASE_NOTES anchor not found exactly once")
    src = src.replace("RELEASE_NOTES = {\n", entry, 1)
    ast.parse(src)                                   # never write a broken module

    cl = CHANGELOG.read_text(encoding="utf-8")
    today = datetime.date.today().isoformat()
    section = f"## [Unreleased]\n\n## [{ver}] - {today}\n\n{n['changelog'].strip()}\n"
    if cl.count("## [Unreleased]\n") != 1:
        sys.exit("CHANGELOG has no single [Unreleased] heading")
    cl = cl.replace("## [Unreleased]\n", section, 1)

    print(f"APP_VERSION {old} -> {ver}"
          + (f", WALLPAPER_VERSION -> {n['wallpaper_version']}" if n.get("wallpaper_version") else ""))
    if a.dry_run:
        print(entry)
        print(section)
        return
    BRIDGE.write_text(src, encoding="utf-8", newline="")
    CHANGELOG.write_text(cl, encoding="utf-8", newline="")
    print("written: bridge.py, CHANGELOG.md -- next: python tests/run_all.py, commit, "
          "pwsh installer/release.ps1")


if __name__ == "__main__":
    main()
