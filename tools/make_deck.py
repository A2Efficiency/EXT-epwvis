#!/usr/bin/env python3
"""
One command: weather stations in, PowerPoint out.

    python tools/make_deck.py "Denver-Centennial AP" "Chicago-OHare"
    python tools/make_deck.py --skip-fetch                  # reuse what is downloaded
    python tools/make_deck.py --search denver               # find an exact station name

Runs fetch_epw.py -> render.mjs -> build_pptx.py in order. Every step is also
runnable on its own; see tools/README.md.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def die(msg):
    sys.exit(f"\n  {msg}\n")


def check_prereqs():
    problems = []
    if shutil.which("node") is None:
        problems.append("node is not on PATH -- install Node.js 18 or newer")
    if not (HERE / "node_modules" / "playwright").exists():
        problems.append("playwright is not installed -- run:  cd tools && npm install "
                        "&& npx playwright install chromium")
    try:
        import pptx  # noqa: F401
    except ImportError:
        problems.append("python-pptx is not installed -- run:  pip install python-pptx")
    if problems:
        die("Setup incomplete:\n    - " + "\n    - ".join(problems))


def run(label, cmd):
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        die(f"{label} failed (exit {result.returncode}); stopping.")


def main():
    ap = argparse.ArgumentParser(
        description="Fetch EPW files, render chart PNGs, and build the deck.")
    ap.add_argument("stations", nargs="*",
                    help="station names, e.g. \"Denver-Centennial AP\"")
    ap.add_argument("--search", metavar="Q",
                    help="list matching station names and exit")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="reuse tools/locations.json and whatever is in weather_files/")
    ap.add_argument("--add", action="store_true",
                    help="add to the existing location list instead of replacing it")

    ap.add_argument("--units", default="IP", choices=["IP", "SI"])
    ap.add_argument("--hbase", help="heating base temperature (default 65F / 18C)")
    ap.add_argument("--cbase", help="cooling base temperature")
    ap.add_argument("--occstart", default="7", help="occupied start, clock hour (default 7)")
    ap.add_argument("--occend", default="19", help="occupied end, clock hour (default 19)")
    ap.add_argument("--scale", default="3", help="PNG device scale (default 3, ~300 DPI)")

    ap.add_argument("--title", default="Climate Analysis")
    ap.add_argument("--client", default="", help="subtitle on the title slide")
    ap.add_argument("--out", default="out/climate-deck.pptx")
    ap.add_argument("--no-title-slide", action="store_true")
    ap.add_argument("--no-comparison-slide", action="store_true",
                    help="omit the closing cross-location summary slide")
    args = ap.parse_args()

    if args.search:
        subprocess.run([sys.executable, "tools/fetch_epw.py", "--search", args.search],
                       cwd=ROOT)
        return

    check_prereqs()

    if not args.skip_fetch:
        if not args.stations:
            ap.error("give at least one station name, or pass --skip-fetch "
                     "to reuse the current list")
        cmd = [sys.executable, "tools/fetch_epw.py"]
        if not args.add:
            cmd.append("--clear")
        run("1/3  Fetching weather files", cmd + args.stations)
    elif args.stations:
        ap.error("--skip-fetch takes no station names")

    cmd = ["node", "tools/render.mjs", "--units", args.units,
           "--scale", args.scale, "--occstart", args.occstart, "--occend", args.occend]
    if args.hbase:
        cmd += ["--hbase", args.hbase]
    if args.cbase:
        cmd += ["--cbase", args.cbase]
    run("2/3  Rendering charts", cmd)

    cmd = [sys.executable, "tools/build_pptx.py",
           "--title", args.title, "--out", args.out]
    if args.client:
        cmd += ["--client", args.client]
    if args.no_title_slide:
        cmd.append("--no-title-slide")
    if args.no_comparison_slide:
        cmd.append("--no-comparison-slide")
    run("3/3  Building PowerPoint", cmd)

    print(f"\nDone.  {args.out}\n")


if __name__ == "__main__":
    main()
