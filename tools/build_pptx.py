#!/usr/bin/env python3
"""
Build a climate deck from out/manifest.json using the A2E PowerPoint template.

Two slides per location, following the reference layout:

  1. Location    -- title, station facts, climate classification, locator map,
                    UTCI hours breakdown, annual temperature, daily profile strip
  2. Degree days -- occupied-hours note, degree days by temperature bin,
                    degree days by month, headline HDD/CDD numbers

Slides are created from the template's own layouts, so master graphics, theme
colours and fonts come along untouched.

    python tools/build_pptx.py
    python tools/build_pptx.py --title "Climate Analysis" --client "Acme Corp"
    python tools/build_pptx.py --no-title-slide --out decks/acme.pptx

Requires: pip install python-pptx
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
except ImportError:
    sys.exit("python-pptx is required:  pip install python-pptx")

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "out" / "manifest.json"
DEFAULT_TEMPLATE = ROOT / "2026_Presentation A2E General Blank.pptx"
DEFAULT_OUT = ROOT / "out" / "climate-deck.pptx"

# Layout names exactly as they appear in the template.
L_TITLE = "1_Title Slide"
L_BLANK = "Blank Light"
L_TITLE_ONLY = "Title Only Light 1"

# Brand theme, read off the template (accent1 / accent3 / dk1 / accent5).
BRAND_ORANGE = RGBColor(0xFF, 0x66, 0x00)
BRAND_TEAL = RGBColor(0x00, 0xA3, 0xB4)
BRAND_INK = RGBColor(0x1A, 0x1F, 0x16)
BRAND_MUTED = RGBColor(0x7A, 0x80, 0x75)

FONT_BODY = "Open Sans"


# ---------------------------------------------------------------- helpers

def resolve(p):
    """Accept paths relative to the repo root as well as absolute ones."""
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


def show(p):
    """Repo-relative for display where possible, absolute otherwise."""
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p


def layout(prs, name):
    for lay in prs.slide_masters[0].slide_layouts:
        if lay.name == name:
            return lay
    raise KeyError(f"layout {name!r} not in template; available: "
                   + ", ".join(l.name for l in prs.slide_masters[0].slide_layouts))


def drop_existing_slides(prs):
    """The template ships sample slides; start from an empty deck."""
    xml_slides = prs.slides._sldIdLst
    for sld in list(xml_slides):
        rId = sld.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        prs.part.drop_rel(rId)
        xml_slides.remove(sld)


def set_text(slide, idx, text):
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == idx:
            ph.text_frame.text = text
            return ph
    return None


def remove_placeholder(slide, idx):
    for ph in list(slide.placeholders):
        if ph.placeholder_format.idx == idx:
            ph._element.getparent().remove(ph._element)
            return


def png_size(path):
    """Pixel dimensions from the PNG IHDR chunk (no Pillow needed)."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def add_picture_fitted(slide, png, left, top, width, height, align="center"):
    """Fit a PNG inside a box, preserving aspect ratio."""
    png = ROOT / png
    iw, ih = png_size(png)
    scale = min(width / iw, height / ih)
    w, h = int(iw * scale), int(ih * scale)
    x = left if align == "left" else int(left + (width - w) / 2)
    y = int(top + (height - h) / 2)
    return slide.shapes.add_picture(str(png), x, y, width=w, height=h)


def textbox(slide, left, top, width, height, lines, size=11,
            color=BRAND_INK, italic=False, align=PP_ALIGN.LEFT, spacing=2):
    """A plain text box; `lines` is a string, or a list of (text, size, bold)."""
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    if isinstance(lines, str):
        lines = [lines]

    for i, line in enumerate(lines):
        text, lsize, lbold = line if isinstance(line, tuple) else (line, size, False)
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        if i:
            para.space_before = Pt(spacing)
        run = para.add_run()
        run.text = text
        run.font.size = Pt(lsize)
        run.font.bold = lbold
        run.font.italic = italic
        run.font.color.rgb = color
        run.font.name = FONT_BODY
    return box


def stat_callout(slide, left, top, width, value, label, color, footnote=None):
    """A big number, its caption, and optionally a bold all-hours comparison."""
    box = slide.shapes.add_textbox(left, top, width, Inches(1.45))
    tf = box.text_frame
    tf.word_wrap = True

    p1 = tf.paragraphs[0]
    r1 = p1.add_run()
    r1.text = value
    r1.font.size = Pt(30)
    r1.font.bold = True
    r1.font.color.rgb = color
    r1.font.name = FONT_BODY

    p2 = tf.add_paragraph()
    r2 = p2.add_run()
    r2.text = label
    r2.font.size = Pt(11)
    r2.font.color.rgb = BRAND_INK
    r2.font.name = FONT_BODY

    if footnote:
        p3 = tf.add_paragraph()
        p3.space_before = Pt(4)
        r3 = p3.add_run()
        r3.text = footnote
        r3.font.size = Pt(12)
        r3.font.bold = True
        r3.font.color.rgb = BRAND_INK
        r3.font.name = FONT_BODY
    return box


# ---------------------------------------------------------------- slides

def add_title_slide(prs, title, subtitle, eyebrow):
    slide = prs.slides.add_slide(layout(prs, L_TITLE))
    set_text(slide, 0, title)
    set_text(slide, 1, subtitle)
    if eyebrow:
        set_text(slide, 15, eyebrow)
    else:
        remove_placeholder(slide, 15)
    return slide


def add_location_slide(prs, loc):
    """Facts and map down the left, temperature charts filling the right."""
    charts = loc.get("charts", {})
    meta = loc.get("meta", {})
    slide = prs.slides.add_slide(layout(prs, L_BLANK))

    textbox(slide, Inches(0.92), Inches(0.28), Inches(8.0), Inches(0.72),
            [(meta.get("station") or loc["name"], 26, True)])

    # --- left column: facts, classification, map, comfort hours ---
    facts = []
    if meta.get("subtitle"):
        facts.append((meta["subtitle"], 9.5, False))
    for label, key in (("Latitude", "latitude"), ("Longitude", "longitude"),
                       ("Elevation", "elevation"), ("Time zone", "timezone"),
                       ("State", "stateName")):
        if meta.get(key):
            facts.append((f"{label}: {meta[key]}", 10, False))
    if facts:
        textbox(slide, Inches(0.92), Inches(1.08), Inches(3.10), Inches(1.55),
                facts, spacing=1)

    # Climate classification gets its own emphasised block.
    cls = []
    if meta.get("ashraeZone"):
        cls.append((f"ASHRAE {meta['ashraeZone']}", 15, True))
    if meta.get("koppenCode"):
        line = "Köppen " + meta["koppenCode"]
        if meta.get("koppenName"):
            line += " — " + meta["koppenName"]
        cls.append((line, 9.5, False))
    if meta.get("koppenDescription"):
        cls.append((meta["koppenDescription"], 9, False))
    if cls:
        textbox(slide, Inches(0.92), Inches(2.70), Inches(3.10), Inches(1.00),
                cls, spacing=1)

    if "location-map" in charts:
        add_picture_fitted(slide, charts["location-map"],
                           Inches(0.80), Inches(3.72), Inches(3.35), Inches(1.95))
    if "utci-categories" in charts:
        add_picture_fitted(slide, charts["utci-categories"],
                           Inches(0.58), Inches(5.55), Inches(3.65), Inches(1.75))

    # --- right column: the two temperature charts ---
    if "temperature-annual" in charts:
        add_picture_fitted(slide, charts["temperature-annual"],
                           Inches(4.30), Inches(0.95), Inches(8.60), Inches(2.70))
    if "temperature-daily-profile" in charts:
        add_picture_fitted(slide, charts["temperature-daily-profile"],
                           Inches(4.30), Inches(3.70), Inches(8.60), Inches(3.45))
    return slide


def fmt_clock(h):
    """19 -> '7pm', 7 -> '7am', 12 -> '12pm'."""
    h = int(h)
    suffix = "am" if h < 12 else "pm"
    display = h if 1 <= h <= 12 else abs(h - 12) or 12
    return f"{display}{suffix}"


def add_degree_day_slide(prs, loc):
    """Both degree-day charts stacked, headline numbers down the right."""
    charts = loc.get("charts", {})
    t = loc.get("totals", {})
    slide = prs.slides.add_slide(layout(prs, L_TITLE_ONLY))

    # The layout title is one 0.51in line spanning the whole slide. Keep it
    # short so it neither wraps (which overflows the box) nor runs under the
    # occupancy note; the station name goes on its own line beneath.
    name = (loc.get("meta", {}) or {}).get("station") or loc["name"]
    set_text(slide, 0, "Degree Days")
    textbox(slide, Inches(0.94), Inches(0.88), Inches(6.90), Inches(0.34),
            [(name, 13, False)], color=BRAND_MUTED)

    if "degree-days-by-temperature" in charts:
        add_picture_fitted(slide, charts["degree-days-by-temperature"],
                           Inches(0.60), Inches(1.28), Inches(9.10), Inches(2.72),
                           align="left")
    if "degree-days-monthly" in charts:
        add_picture_fitted(slide, charts["degree-days-monthly"],
                           Inches(0.60), Inches(4.20), Inches(9.10), Inches(2.58),
                           align="left")

    # --- headline numbers + the assumptions behind them ---
    if t:
        unit = t.get("unit", "")
        stat_callout(slide, Inches(10.00), Inches(1.30), Inches(2.90),
                     f"{t['hddOccupied']:,}",
                     f"heating degree days ({unit}, occupied)", BRAND_ORANGE,
                     footnote=f"{t['hddAll']:,} all hours")
        stat_callout(slide, Inches(10.00), Inches(3.15), Inches(2.90),
                     f"{t['cddOccupied']:,}",
                     f"cooling degree days ({unit}, occupied)", BRAND_TEAL,
                     footnote=f"{t['cddAll']:,} all hours")

        pct = t["occupiedHours"] / t["totalHours"] * 100 if t["totalHours"] else 0
        textbox(slide, Inches(10.00), Inches(5.05), Inches(2.95), Inches(1.60),
                [("Assumptions", 11, True),
                 (f"Base {t['hBase']:g}°F heating and cooling.", 9.5, False),
                 (f"Occupied {int(t['occStart'])}:00–{int(t['occEnd'])}:00, "
                  f"{t['occupiedHours']:,} of {t['totalHours']:,} h "
                  f"({pct:.0f}%).", 9.5, False)],
                color=BRAND_MUTED, spacing=3)

        textbox(slide, Inches(0.60), Inches(6.92), Inches(8.60), Inches(0.36),
                [(f"Filter shows {fmt_clock(t['occStart'])} to "
                  f"{fmt_clock(t['occEnd'])} occupied hours "
                  f"and transparent is all data", 12, False)],
                italic=True)
    return slide


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--title", default="Climate Analysis")
    ap.add_argument("--client", default="", help="subtitle on the title slide")
    ap.add_argument("--eyebrow", default="Weather File Review")
    ap.add_argument("--no-title-slide", action="store_true")
    args = ap.parse_args()

    man_path = resolve(args.manifest)
    if not man_path.exists():
        sys.exit(f"missing {man_path} -- run tools/render.mjs first")
    manifest = json.loads(man_path.read_text(encoding="utf-8"))

    tpl = resolve(args.template)
    if not tpl.exists():
        sys.exit(f"missing template {tpl}")

    prs = Presentation(str(tpl))
    drop_existing_slides(prs)

    locs = manifest.get("locations", [])
    if not locs:
        sys.exit("manifest has no locations")

    if not args.no_title_slide:
        subtitle = args.client or " · ".join(
            (l.get("meta", {}) or {}).get("station") or l["name"] for l in locs)
        add_title_slide(prs, args.title, subtitle, args.eyebrow)

    for loc in locs:
        add_location_slide(prs, loc)
        add_degree_day_slide(prs, loc)

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    print(f"wrote {show(out)}  "
          f"({len(prs.slides._sldIdLst)} slides, {len(locs)} location(s))")


if __name__ == "__main__":
    main()
