#!/usr/bin/env python3
"""
Fetch TMYx EPW files from climate.onebuilding.org into weather_files/ and
register them in tools/locations.json for tools/render.mjs.

Station names are resolved against the index the viewer already ships in
data/stations.js, so there is no scraping and no extra dependency -- stdlib only.

    python tools/fetch_epw.py --search denver
    python tools/fetch_epw.py "Denver-Centennial AP" "Chicago-OHare Intl AP"
    python tools/fetch_epw.py --clear "Seattle-Tacoma Intl AP"

--clear replaces locations.json instead of appending to it.
"""
import argparse
import io
import json
import re
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIONS_JS = ROOT / "data" / "stations.js"
WEATHER_DIR = ROOT / "weather_files"
LOCATIONS = ROOT / "tools" / "locations.json"

BASE = "https://climate.onebuilding.org/"
SUFFIX = "_TMYx.2009-2023.zip"

# climate.onebuilding.org serves a self-signed cert; the viewer's own indexer
# (build_station_index.py) disables verification for the same reason.
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def load_stations():
    if not STATIONS_JS.exists():
        sys.exit(f"missing {STATIONS_JS}")
    text = STATIONS_JS.read_text(encoding="utf-8")
    start = text.index("[")
    end = text.rindex("]") + 1
    return json.loads(text[start:end])


def search(stations, query):
    q = query.lower().strip()
    exact = [s for s in stations if s["n"].lower() == q]
    if exact:
        return exact
    # Fall back to all-terms-present matching, so "denver ap" finds the airport.
    terms = q.replace("-", " ").split()
    return [s for s in stations
            if all(t in s["n"].lower().replace("-", " ") for t in terms)]


def slugify(name):
    s = re.sub(r"\(.*?\)", "", name)                 # drop the "(CO, USA)" tail
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "station"


def fetch(station):
    url = BASE + station["u"] + SUFFIX
    print(f"  downloading {url.rsplit('/', 1)[-1]} …", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "epwvis-deck/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r:
        blob = r.read()

    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = [n for n in zf.namelist() if n.lower().endswith(".epw")]
    if not names:
        raise RuntimeError(f"no .epw inside {url}")

    # The sibling .stat carries the authoritative ASHRAE 169-2021 climate zone
    # and Koppen class. Deriving those from the EPW is unreliable: the A/B
    # moisture letter needs precipitation the EPW reports too coarsely (Denver
    # computes as "moist" by 5 mm, but is published 5B), and the EPW-derived
    # Koppen misses too (Dfa for Denver, where the .stat correctly says BSk).
    stats = [n for n in zf.namelist() if n.lower().endswith(".stat")]
    stat = zf.read(stats[0]) if stats else None
    return zf.read(names[0]), stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="station names to fetch")
    ap.add_argument("--search", metavar="Q", help="list matching stations and exit")
    ap.add_argument("--clear", action="store_true",
                    help="replace locations.json instead of appending")
    args = ap.parse_args()

    stations = load_stations()

    if args.search:
        hits = search(stations, args.search)
        print(f"{len(hits)} match(es) for {args.search!r}:")
        for s in hits[:60]:
            print("  " + s["n"])
        if len(hits) > 60:
            print(f"  … and {len(hits) - 60} more")
        return

    if not args.names:
        ap.error("give at least one station name, or use --search")

    WEATHER_DIR.mkdir(exist_ok=True)
    entries = [] if args.clear or not LOCATIONS.exists() \
        else json.loads(LOCATIONS.read_text(encoding="utf-8"))
    by_slug = {e["slug"]: e for e in entries}

    for name in args.names:
        hits = search(stations, name)
        if not hits:
            print(f"NO MATCH  {name}  (try --search)")
            continue
        if len(hits) > 1:
            print(f"AMBIGUOUS {name} -> {len(hits)} matches; using {hits[0]['n']!r}")
            for s in hits[1:6]:
                print(f"            other: {s['n']}")
        station = hits[0]
        slug = slugify(station["n"])
        try:
            epw, stat = fetch(station)
        except Exception as exc:
            print(f"FAILED    {station['n']}: {exc}")
            continue

        path = WEATHER_DIR / f"{slug}.epw"
        path.write_bytes(epw)
        if stat:
            (WEATHER_DIR / f"{slug}.stat").write_bytes(stat)

        entry = {
            "slug": slug,
            "name": station["n"],
            "epw": f"weather_files/{slug}.epw",
        }
        by_slug[slug] = entry
        print(f"OK        {station['n']}  ->  {path.relative_to(ROOT)}"
              + ("  (+ .stat)" if stat else "  (no .stat -- zone will be computed)"))

    out = list(by_slug.values())
    LOCATIONS.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\n{LOCATIONS.relative_to(ROOT)}: {len(out)} location(s)")


if __name__ == "__main__":
    main()
