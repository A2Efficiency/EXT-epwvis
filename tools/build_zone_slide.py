#!/usr/bin/env python3
"""
Put the climate-zone charts on 17x11 in slides.

  1. the January/July daily-profile grid, one image
  2. the per-location dew-point comfort bands, one small chart each

    python tools/build_zone_slide.py
    python tools/build_zone_slide.py --title "Climate Comparison" --client "Acme"
    python tools/build_zone_slide.py --png out/zonegrid/climate-zones.png

Reads out/zonegrid/climate-zones.json for the image path and the column list,
so the footnote names the stations and zones actually drawn.

The slide is 17x11 in, not the template's own size, so this builds a fresh
Presentation rather than opening the A2E template -- a template's slide size
applies to every slide in the file and cannot be changed for one. Brand colours
and the body font are set explicitly instead.

Requires: pip install python-pptx
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
except ImportError:
    sys.exit("python-pptx is required:  pip install python-pptx")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "out" / "zonegrid" / "climate-zones.json"
DEFAULT_OUT = ROOT / "out" / "zonegrid" / "climate-zones-17x11.pptx"

SLIDE_W = Inches(17)
SLIDE_H = Inches(11)

# Brand theme, same values build_pptx.py reads off the template.
BRAND_INK = RGBColor(0x1A, 0x1F, 0x16)
BRAND_MUTED = RGBColor(0x7A, 0x80, 0x75)
BRAND_ORANGE = RGBColor(0xFF, 0x66, 0x00)
FONT_BODY = "Open Sans"


def resolve(p):
    """Accept paths relative to the repo root as well as absolute ones."""
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


def show(p):
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p


def textbox(slide, left, top, width, height, text, size, bold=False,
            color=BRAND_INK, align=None):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    para = tf.paragraphs[0]
    if align is not None:
        para.alignment = align
    run = para.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = FONT_BODY
    run.font.color.rgb = color
    return box


def png_size(path):
    """Width and height out of the PNG's own IHDR."""
    from struct import unpack
    with open(path, "rb") as fh:
        head = fh.read(24)
    return unpack(">II", head[16:24])


def fit(png_w, png_h, box_w, box_h):
    """Largest centred rect with the image's aspect ratio inside the box."""
    scale = min(box_w / png_w, box_h / png_h)
    w = int(png_w * scale)
    h = int(png_h * scale)
    return w, h, (box_w - w) // 2, (box_h - h) // 2


def main():
    ap = argparse.ArgumentParser(
        description="Build a 17x11 in slide holding the climate-zone grid.")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--png", default=None,
                    help="override the image named in the manifest")
    ap.add_argument("--title", default="Typical Daily Temperature by ASHRAE Climate Zone")
    ap.add_argument("--client", default=None)
    ap.add_argument("--bands-title",
                    default="Outdoor Dew Point — Indoor Comfort Bands")
    ap.add_argument("--no-bands", action="store_true",
                    help="skip the second slide")
    ap.add_argument("--band-cols", type=int, default=4,
                    help="comfort-band charts per row on slide 2")
    ap.add_argument("--no-map", action="store_true",
                    help="skip the study locator map on slide 1")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    man_path = resolve(args.manifest)
    if not man_path.exists():
        sys.exit(f"\n  No manifest at {show(man_path)}."
                 f"\n  Run:  node tools/render_zone_grid.mjs\n")
    man = json.loads(man_path.read_text(encoding="utf-8"))

    png = resolve(args.png) if args.png else resolve(man["png"])
    if not png.exists():
        sys.exit(f"\n  Image not found: {show(png)}\n")

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    slide = prs.slides.add_slide(prs.slide_layouts[6])   # blank

    margin = Inches(0.55)
    inner_w = SLIDE_W - 2 * margin

    # The study map sits top-right; the title block takes the width left of it.
    site_map = None if args.no_map else (
        resolve(man["map"]) if man.get("map") else None)
    if site_map is not None and not site_map.exists():
        site_map = None

    map_w = map_h = 0
    if site_map is not None:
        mw, mh = png_size(site_map)
        map_h = int(Inches(1.95))
        map_w = int(map_h * mw / mh)
        slide.shapes.add_picture(str(site_map),
                                 margin + inner_w - map_w, Inches(0.30),
                                 width=map_w, height=map_h)

    title_w = inner_w - (map_w + int(Inches(0.25)) if map_w else 0)
    textbox(slide, margin, Inches(0.42), title_w, Inches(0.55),
            args.title, 26, bold=True, align=PP_ALIGN.CENTER)

    months = man.get("months", [1, 7])
    month_names = ["January", "February", "March", "April", "May", "June", "July",
                   "August", "September", "October", "November", "December"]
    sub = (f"{len(man['columns'])} locations, "
           + " and ".join(month_names[m - 1] for m in months)
           + f" · dry bulb and dew point · hourly min–max envelope with the "
           + ("hourly mean · one shared temperature scale" if man.get("shareY", "all") == "all"
              else "hourly mean · one temperature scale per month"))
    if args.client:
        sub = f"{args.client}  ·  {sub}"
    textbox(slide, margin, Inches(1.02), title_w, Inches(0.32), sub, 13,
            color=BRAND_MUTED, align=PP_ALIGN.CENTER)

    # Image box: below whichever of the title block and the map runs deeper.
    box_top = Inches(2.30) if site_map is not None else Inches(1.52)
    box_h = SLIDE_H - box_top - Inches(0.95)
    png_w, png_h = png_size(png)
    w, h, dx, dy = fit(png_w, png_h, int(inner_w), int(box_h))
    slide.shapes.add_picture(str(png), margin + Emu(dx), box_top + Emu(dy),
                             width=Emu(w), height=Emu(h))

    zones = ", ".join(f"{c['zone']} {c['city']}" for c in man["columns"])
    foot = (f"ASHRAE 169 climate zones read from each weather file’s .stat, "
            f"never computed: {zones}. "
            f"Source: {man.get('source', 'weather_data')}, TMYx typical-year files.")
    textbox(slide, margin, SLIDE_H - Inches(0.80), inner_w, Inches(0.5),
            foot, 10, color=BRAND_MUTED)

    # ---------------------------------------------------------- slide 2
    bands = [] if args.no_bands else [
        c for c in man["columns"]
        if c.get("bandPng") and resolve(c["bandPng"]).exists()]
    n_bands = 0
    if bands:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        textbox(slide, margin, Inches(0.42), inner_w, Inches(0.55),
                args.bands_title, 26, bold=True, align=PP_ALIGN.CENTER)
        textbox(slide, margin, Inches(1.02), inner_w, Inches(0.32),
                "RH thresholds transposed to dew point at 70°F indoors (dry "
                "side) and 75°F (humid side) · hours per year · every chart on "
                "the same hour scale, so bars compare across locations", 13,
                color=BRAND_MUTED, align=PP_ALIGN.CENTER)

        # 4 across. The charts are drawn compact (trimmed label column and
        # gutter) specifically so this many fit without the labels shrinking.
        cols, gap = args.band_cols, Inches(0.18)
        cell_w = (inner_w - gap * (cols - 1)) // cols
        bw, bh = png_size(resolve(bands[0]["bandPng"]))
        cell_h = int(cell_w * bh / bw)
        top0 = Inches(1.58)

        for i, c in enumerate(bands):
            r, k = divmod(i, cols)
            slide.shapes.add_picture(
                str(resolve(c["bandPng"])),
                margin + k * (cell_w + gap),
                top0 + r * (cell_h + gap),
                width=int(cell_w), height=int(cell_h))
        n_bands = len(bands)

        rows = -(-n_bands // cols)
        foot_top = top0 + rows * (cell_h + gap) + Inches(0.10)
        textbox(slide, margin, min(foot_top, SLIDE_H - Inches(0.80)),
                inner_w, Inches(0.6),
                "Bands are the published indoor relative-humidity comfort "
                "thresholds transposed to dew point: sensible heating and "
                "cooling leave dew point unchanged, so the outdoor dew point is "
                "the zone dew point of a space on outdoor air with no "
                "dehumidification. Bounds are half-open, so all 8,760 hours land "
                "in exactly one band.", 10, color=BRAND_MUTED)

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))

    print(f"\n  Slide  : 17 x 11 in")
    print(f"  Image  : {show(png)}  ({png_w}x{png_h} px)")
    print(f"  Placed : {w / 914400:.2f} x {h / 914400:.2f} in "
          f"({png_w / (w / 914400):.0f} DPI)")
    print(f"  Map    : {show(site_map)}" if site_map is not None
          else "  Map    : none")
    print(f"  Slide 2: {n_bands} comfort-band charts" if n_bands
          else "  Slide 2: skipped (no band charts in the manifest)")
    print(f"  Wrote  : {show(out)}\n")


if __name__ == "__main__":
    main()
