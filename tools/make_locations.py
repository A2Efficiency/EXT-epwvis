#!/usr/bin/env python3
"""
Write a locations.json for a directory of .epw files that are already on disk.

fetch_epw.py produces this file as a side effect of downloading; this is the
equivalent for weather files that arrived some other way, so render.mjs can be
pointed at them without a network round trip.

    python tools/make_locations.py                       # weather_data -> tools/locations-weather-data.json
    python tools/make_locations.py --dir weather_files --out tools/locations.json

Names and slugs come from the EPW's own LOCATION header (field 1 is the station,
2 the state, 3 the country), not from the file name, which on OneBuilding files
is a mangled version of the same thing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "weather_data"
DEFAULT_OUT = ROOT / "tools" / "locations-weather-data.json"


def resolve(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


def slugify(text):
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-+", "-", s)


def station(epw_path):
    """(name, state, country) from the LOCATION header, or None if unreadable."""
    with open(epw_path, "r", encoding="utf-8", errors="replace") as fh:
        first = fh.readline()
    parts = first.split(",")
    if len(parts) < 4 or parts[0].strip().upper() != "LOCATION":
        return None
    # OneBuilding writes "Houston-Bush.Intercontinental.AP"; the dots and dashes
    # are word separators, not punctuation.
    name = re.sub(r"[._]+", " ", parts[1]).replace("-", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return name, parts[2].strip(), parts[3].strip()


def main():
    ap = argparse.ArgumentParser(
        description="Build a render.mjs locations.json from a folder of .epw files.")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    src = resolve(args.dir)
    if not src.is_dir():
        sys.exit(f"\n  Not a directory: {src}\n")

    rows = []
    for epw in sorted(src.glob("*.epw")):
        info = station(epw)
        if info is None:
            print(f"  skipping {epw.name}: no LOCATION header")
            continue
        name, state, country = info
        rel = epw.relative_to(ROOT).as_posix()
        stat = epw.with_suffix(".stat")
        rows.append({
            "slug": slugify(f"{name}-{state}"),
            "name": f"{name} ({state}, {country})" if state else name,
            "epw": rel,
            # dashboard.html derives the .stat path from the .epw path, so the
            # sibling has to be there; say so loudly rather than silently
            # falling back to the computed climate zone.
            "stat": stat.relative_to(ROOT).as_posix() if stat.exists() else None,
        })

    if not rows:
        sys.exit(f"\n  No .epw files in {src}\n")

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    missing = [r["name"] for r in rows if not r["stat"]]
    print(f"\n  {len(rows)} locations -> {out.relative_to(ROOT)}")
    for r in rows:
        print(f"    {r['slug']:<34} {r['name']}")
    if missing:
        print(f"\n  WARNING: no sibling .stat for: {', '.join(missing)}"
              f"\n  Those slides will show a computed climate zone, not a published one.")
    print()


if __name__ == "__main__":
    main()
