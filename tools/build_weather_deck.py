#!/usr/bin/env python3
"""
Build a multi-location weather deck: summary, zone-by-zone comparison grids,
and the per-location backup slides from build_pptx.py as an appendix.

Inputs (run these first):
    node tools/render.mjs --locations tools/locations-lllc.json --out out/lllc
                                                      -> out/lllc/manifest.json  (appendix)
    node tools/render_grid.mjs --out out/lllc/grid    -> out/lllc/grid/grid.json (grids)

    python tools/build_weather_deck.py
    python tools/build_weather_deck.py --out decks/LLLC.pptx

The station set, the roles and the grouping into slides come from the config
that render_grid.mjs read (tools/lllc-weather.json). Every number quoted in a
takeaway is computed from grid.json, never typed by hand.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pptx as B  # noqa: E402

from pptx.util import Inches, Pt, Emu  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402

ROOT = B.ROOT
L_SECTION = "Section Header 1"
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xF4, 0xF5, 0xF0)
SOFT = RGBColor(0x4A, 0x52, 0x45)


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def t(n):
    """Temperature for prose: whole degrees with a real minus sign."""
    n = round(n)
    return ("−" if n < 0 else "") + f"{abs(n)}°F"


def pct_diff(a, b):
    return (a - b) / b * 100


# ------------------------------------------------------------------ helpers

def run_fmt(run, size, bold=False, color=B.BRAND_INK, italic=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = B.FONT_BODY


def rich_box(slide, left, top, width, height, paras, anchor=None):
    """paras: list of paragraphs; each a list of (text, size, bold, color)."""
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    if anchor:
        tf.vertical_anchor = anchor
    for i, runs in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if i:
            p.space_before = Pt(3)
        for text, size, bold, color in runs:
            run_fmt(p.add_run(), size, bold, color)
            p.runs[-1].text = text
    return box


def subtitle(slide, text):
    B.textbox(slide, Inches(0.94), Inches(0.86), Inches(11.4), Inches(0.34),
              [(text, 13, False)], color=B.BRAND_MUTED)


def takeaway(slide, text, top=6.86):
    B.textbox(slide, Inches(0.60), Inches(top), Inches(11.35), Inches(0.5),
              [(text, 11.5, False)], italic=True)


def marker(slide, kind, color, left, top, size=0.16):
    s = Inches(size)
    if kind == "doe":
        shp = slide.shapes.add_shape(MSO_SHAPE.DIAMOND, left, top, s, s)
    else:
        shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, s, s)
    shp.shadow.inherit = False
    if kind == "proposed" or kind == "doe":
        shp.fill.solid()
        shp.fill.fore_color.rgb = color
        shp.line.color.rgb = WHITE
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = WHITE
        shp.line.color.rgb = color
        shp.line.width = Pt(2.25)
    return shp


def section_slide(prs, title, blurb=None):
    slide = prs.slides.add_slide(B.layout(prs, L_SECTION))
    B.set_text(slide, 0, title)
    if blurb:
        ph = [p for p in slide.placeholders if p.placeholder_format.idx == 0][0]
        top = ph.top + ph.height + Inches(0.1)
        B.textbox(slide, ph.left, top, ph.width, Inches(1.2),
                  [(blurb, 14, False)], color=B.BRAND_MUTED)
    return slide


# ------------------------------------------------------------------ slides

def add_map_slide(prs, grid, man_meta):
    cfg = grid["config"]
    locs = {l["slug"]: l for l in cfg["locations"]}
    slide = prs.slides.add_slide(B.layout(prs, B.L_TITLE_ONLY))
    B.set_text(slide, 0, "Locations in the Analysis")
    subtitle(slide, "Four modeled weather files (two in 5B), each set against the "
                    "DOE/PNNL prototype city and populated NEEA cities")

    B.add_picture_fitted(slide, grid["charts"]["grid-map"],
                         Inches(0.45), Inches(1.30), Inches(6.55), Inches(5.45))

    # --- zone table, right ---
    x0 = Inches(7.15)
    # Modeled cities per zone come from the config's "modeled" flag.
    notes = {"4C": "Seattle is also the DOE/PNNL 4C city",
             "5B": "Two 5B runs; Boise has the highest CDD",
             "6B": "In place of Helena, MT"}
    rows = []
    for zone in ("4C", "5B", "6B"):
        zl = [l["slug"] for l in cfg["locations"] if l["codeZone"] == zone]
        mod = [s for s in zl if locs[s].get("modeled")]
        rows.append((zone, mod, notes[zone], [s for s in zl if s not in mod]))
    y = Inches(1.40)
    for zone, slug, note, refs in rows:
        col = rgb(cfg["zoneColors"][zone])
        chip = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x0, y, Inches(0.62), Inches(0.42))
        chip.shadow.inherit = False
        chip.fill.solid(); chip.fill.fore_color.rgb = col; chip.line.fill.background()
        tf = chip.text_frame
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        r = tf.paragraphs[0].add_run(); r.text = zone; run_fmt(r, 15, True, WHITE)

        ref_txt = "; ".join(
            f"{locs[s]['city']} ({'DOE/PNNL' if locs[s]['roleKind'] == 'doe' else 'NEEA'})"
            for s in refs)
        rich_box(slide, x0 + Inches(0.78), y - Inches(0.06), Inches(5.0), Inches(1.0), [
            [(" + ".join(locs[m]["city"] for m in slug), 15, True, B.BRAND_INK),
             ("   " + note, 10, False, B.BRAND_MUTED)],
            [("Compared with: ", 10, True, SOFT), (ref_txt, 10, False, SOFT)],
        ])
        y += Inches(1.08)

    rich_box(slide, x0, y - Inches(0.02), Inches(5.6), Inches(0.5), [
        [("5C (Port Angeles) ", 10, True, B.BRAND_MUTED),
         ("is not modeled: NEEA chose 4C and 5B for Washington code savings; 5C is too small.",
          10, False, B.BRAND_MUTED)]])

    # --- legend for the map symbols ---
    ly = Inches(5.45)
    B.textbox(slide, x0, ly, Inches(3), Inches(0.3), [("Map key", 11, True)])
    items = [("proposed", "Proposed modeling location"),
             ("doe", "DOE/PNNL prototype city for the zone"),
             ("other", "Comparison city (populated NEEA / prior pick)")]
    for i, (kind, label) in enumerate(items):
        yy = ly + Inches(0.34 + i * 0.27)
        marker(slide, kind, B.BRAND_INK if kind != "other" else B.BRAND_INK, x0 + Inches(0.03), yy + Inches(0.03))
        B.textbox(slide, x0 + Inches(0.28), yy - Inches(0.05), Inches(4.5), Inches(0.3),
                  [(label, 10, False)])
    B.textbox(slide, x0 + Inches(3.55), ly + Inches(0.32), Inches(2.4), Inches(0.9),
              [("Colour = code climate zone", 10, False),
               ("Shaded states = NEEA region", 10, False)], color=SOFT, spacing=4)

    B.textbox(slide, Inches(0.60), Inches(6.86), Inches(11.3), Inches(0.4),
              [("Weather: OneBuilding TMYx 2011–2025 typical-year files for each airport "
                "station. Station list per NEEA (K. Bae, 10/29/2026; approved 10/30).", 9.5, False)],
              color=B.BRAND_MUTED)
    return slide


METRICS = [
    # label, key, formatter, source
    ("Heating degree days, base 65°F", "hdd", lambda v: f"{v:,.0f}"),
    ("Cooling degree days, base 65°F", "cdd", lambda v: f"{v:,.0f}"),
    ("Coldest hour", "min", lambda v: t(v)),
    ("Coldest 10% of hours are below", "p10", lambda v: t(v)),
    ("Median hour", "p50", lambda v: t(v)),
    ("Hottest 10% of hours are above", "p90", lambda v: t(v)),
    ("Hottest hour", "max", lambda v: t(v)),
    ("ASHRAE 99.6% heating design", "designHeating996", lambda v: t(v)),
    ("ASHRAE 0.4% cooling design", "designCooling04", lambda v: t(v)),
    ("Outdoor hours with no thermal stress (UTCI)", "utciNoStressPct", lambda v: f"{v:.0f}%"),
    ("Elevation", "elevationFt", lambda v: f"{v:,.0f} ft"),
    ("Zone from station data (ASHRAE 2025)", "stationZone", lambda v: v),
]


def cell_text(cell, text, size=10, bold=False, color=B.BRAND_INK, align=PP_ALIGN.CENTER, fill=None):
    cell.text = ""
    p = cell.text_frame.paragraphs[0]
    p.alignment = align
    r = p.add_run(); r.text = text
    run_fmt(r, size, bold, color)
    cell.margin_left = cell.margin_right = Inches(0.05)
    cell.margin_top = cell.margin_bottom = Inches(0.02)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    if fill is not None:
        cell.fill.solid(); cell.fill.fore_color.rgb = fill
    else:
        cell.fill.background()


def merged_stats(grid, man_meta, slug):
    s = dict(grid["stats"][slug])
    m = man_meta.get(slug, {})
    s["designHeating996"] = m.get("designHeating996")
    s["designCooling04"] = m.get("designCooling04")
    s["stationZone"] = m.get("ashraeZoneCode", "")
    return s


def add_numbers_slide(prs, grid, man_meta):
    cfg = grid["config"]
    locs = {l["slug"]: l for l in cfg["locations"]}
    order = [("4C", ["seattle-tacoma-intl-ap", "portland-intl-ap", "eugene-ap-sweet-field"]),
             ("5B", ["boise-ap-gowen-field-angb", "spokane-intl-ap", "denver-intl-ap",
                     "redmond-muni-ap-roberts-field", "yakima-af-mcallister-field"]),
             ("6B", ["missoula-intl-ap", "great-falls", "helena-rgnl-ap"])]
    slugs = [s for _, ss in order for s in ss]
    st = {s: merged_stats(grid, man_meta, s) for s in slugs}

    slide = prs.slides.add_slide(B.layout(prs, B.L_TITLE_ONLY))
    B.set_text(slide, 0, "Locations in Numbers")
    subtitle(slide, "Modeled locations in bold · all 8,760 hours of the typical year")

    nrows, ncols = len(METRICS) + 2, 1 + len(slugs)
    left, top = Inches(0.60), Inches(1.30)
    firsts = {s for _, ss in order for s in ss if locs[s].get("modeled")}
    # 12.15in of table across the slide, whatever the city count.
    cw = min(1.04, (12.15 - 2.75) / len(slugs))
    widths = [Inches(2.75)] + [Inches(cw)] * len(slugs)
    shape = slide.shapes.add_table(nrows, ncols, left, top, sum(widths, Emu(0)),
                                   Inches(0.36) * nrows)
    tbl = shape.table
    tbl.first_row = False
    tbl.horz_banding = False
    for i, w in enumerate(widths):
        tbl.columns[i].width = w
    for r in range(nrows):
        tbl.rows[r].height = Inches(0.36 if r > 1 else 0.34)

    # Row 0: zone bands, merged over each group's three columns.
    cell_text(tbl.cell(0, 0), "", fill=None)
    cell_text(tbl.cell(1, 0), "", fill=None)
    c = 1
    for zone, ss in order:
        tbl.cell(0, c).merge(tbl.cell(0, c + len(ss) - 1))
        cell_text(tbl.cell(0, c), f"Climate zone {zone}", 12, True, WHITE,
                  fill=rgb(cfg["zoneColors"][zone]))
        for j, s in enumerate(ss):
            cell_text(tbl.cell(1, c + j), locs[s]["short"], 10.5, j == 0, B.BRAND_INK, fill=LIGHT)
        c += len(ss)

    for r, (label, key, fmt) in enumerate(METRICS, start=2):
        band = LIGHT if r % 2 else None
        cell_text(tbl.cell(r, 0), label, 10, False, SOFT, PP_ALIGN.LEFT, fill=band)
        for j, s in enumerate(slugs):
            v = st[s].get(key)
            first = s in firsts
            cell_text(tbl.cell(r, 1 + j), "—" if v is None else fmt(v), 10.5, first,
                      B.BRAND_INK, fill=band)

    hdd = [st[s]["hdd"] for s in slugs]
    cdd = [st[s]["cdd"] for s in slugs]
    hi_c = max(slugs, key=lambda s: st[s]["cdd"])
    takeaway(slide,
             f"Heating separates the zones cleanly (HDD65 {min(hdd):,}–{max(hdd):,}); cooling is small "
             f"everywhere ({min(cdd):,}–{max(cdd):,} CDD65) and does not follow zone order — "
             f"{locs[hi_c]['short']} is the most cooling-heavy city in the set.", top=6.62)
    B.textbox(slide, Inches(0.60), Inches(7.02), Inches(11.3), Inches(0.4),
              [("Code zones are county assignments. The station-level zone from the 2025 ASHRAE "
                "Handbook data (last row) differs for Boise, Spokane, Redmond and Missoula; the appendix "
                "slides report that station value.", 9, False)], color=B.BRAND_MUTED)
    return slide


COL_HEADS = [
    ("Outdoor thermal comfort (UTCI)", "% of hours in each stress category, cold → hot"),
    ("Heating & cooling degree days", "Monthly °F·day, base 65°F, all hours"),
    ("Temperature extremes", "Month min–max (thin), middle 80% (box), median (line); "
                             "dashed = coldest / hottest 10% of the year"),
]


def add_grid_slide(prs, grid, man_meta, title, sub, rows, take):
    """Rows of cities x three metric columns, every chart on a shared scale."""
    cfg = grid["config"]
    locs = {l["slug"]: l for l in cfg["locations"]}
    charts = grid["charts"]
    slide = prs.slides.add_slide(B.layout(prs, B.L_TITLE_ONLY))
    B.set_text(slide, 0, title)
    subtitle(slide, sub)

    lab_l, lab_w = Inches(0.50), Inches(1.95)
    col_l = [Inches(2.50), Inches(6.08), Inches(9.66)]
    col_w = Inches(3.52)
    head_t = Inches(1.24)
    row_t, row_h = Inches(1.80), Inches(1.68)

    for i, (h, s) in enumerate(COL_HEADS):
        rich_box(slide, col_l[i], head_t, col_w, Inches(0.55),
                 [[(h, 12, True, B.BRAND_INK)], [(s, 8.5, False, B.BRAND_MUTED)]])

    for r, slug in enumerate(rows):
        loc = locs[slug]
        y = row_t + row_h * r
        color = rgb(cfg["zoneColors"][loc["codeZone"]])
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, lab_l, y + Inches(0.12),
                                     Inches(0.07), row_h - Inches(0.30))
        bar.shadow.inherit = False
        bar.fill.solid(); bar.fill.fore_color.rgb = color; bar.line.fill.background()
        station_zone = man_meta.get(slug, {}).get("ashraeZoneCode", "")
        zl = f"Code zone {loc['codeZone']}"
        if station_zone and station_zone != loc["codeZone"]:
            zl += f" · station data {station_zone}"
        rich_box(slide, lab_l + Inches(0.15), y + Inches(0.10), lab_w - Inches(0.15), row_h - Inches(0.2), [
            [(loc["city"], 14, True, B.BRAND_INK)],
            [(loc["role"], 9.5, loc["roleKind"] == "proposed", color)],
            [(zl, 8.5, False, B.BRAND_MUTED)],
        ])
        for i, k in enumerate(("utci", "dd", "temp")):
            name = f"grid-{k}-{slug}"
            if name in charts:
                B.add_picture_fitted(slide, charts[name], col_l[i], y, col_w, row_h, align="left")

    if take:
        takeaway(slide, take, top=row_t / 914400 + row_h / 914400 * len(rows) + 0.04
                 if len(rows) < 3 else 6.86)
    return slide


# ------------------------------------------------------------------ narrative

def takeaways(grid, man_meta):
    S = {k: merged_stats(grid, man_meta, k) for k in grid["stats"]}
    bo, sp, de = S["boise-ap-gowen-field-angb"], S["spokane-intl-ap"], S["denver-intl-ap"]
    se, po, eu = S["seattle-tacoma-intl-ap"], S["portland-intl-ap"], S["eugene-ap-sweet-field"]
    mi, gf, he = S["missoula-intl-ap"], S["great-falls"], S["helena-rgnl-ap"]

    t5b = (f"Boise and Spokane bracket 5B: Spokane carries {pct_diff(sp['hdd'], bo['hdd']):.0f}% more HDD65, "
           f"Boise {pct_diff(bo['cdd'], sp['cdd']):.0f}% more CDD65 ({bo['cdd']:,} vs {sp['cdd']:,}) with a hottest-10% "
           f"threshold {bo['p90'] - sp['p90']:.0f}°F higher. Denver, the DOE/PNNL city, falls between them — "
           f"Boise-like heating ({de['hdd']:,}), cooling in the middle ({de['cdd']:,}).")

    t4c = (f"Heating is near-identical across 4C (HDD65 {min(se['hdd'], po['hdd'], eu['hdd']):,}–"
           f"{max(se['hdd'], po['hdd'], eu['hdd']):,}). Seattle has the mildest summer: "
           f"{se['cdd']:,} CDD65 vs {po['cdd']:,} Portland / {eu['cdd']:,} Eugene, and its hottest 10% "
           f"of hours start {po['p90'] - se['p90']:.0f}°F lower.")

    t6b = (f"Annual heating is within {abs(pct_diff(he['hdd'], gf['hdd'])):.0f}% across 6B; summers are "
           f"near-identical (90% thresholds within {max(mi['p90'], gf['p90'], he['p90']) - min(mi['p90'], gf['p90'], he['p90']):.0f}°F). "
           f"Missoula's cold tail is milder: coldest hour {t(mi['min'])} vs {t(gf['min'])} at Great Falls, "
           f"99.6% design {t(mi['designHeating996'])} vs {t(gf['designHeating996'])}.")

    east = {
        "hdd": pct_diff(mi["hdd"], sp["hdd"]),
        "cdd": pct_diff(mi["cdd"], sp["cdd"]),
        "p50": sp["p50"] - mi["p50"],
        "p10": sp["p10"] - mi["p10"],
        "p90": sp["p90"] - mi["p90"],
        "design": sp["designHeating996"] - mi["designHeating996"],
    }
    teast = (f"Yes for heating, marginal for cooling: Missoula carries {east['hdd']:.0f}% more HDD65 "
             f"({mi['hdd']:,} vs {sp['hdd']:,}) and its median hour is {east['p50']:.0f}°F colder, "
             f"while summers differ little (hottest 10% within {abs(east['p90']):.0f}°F; CDD65 "
             f"{mi['cdd']:,} vs {sp['cdd']:,}).")
    return t5b, t4c, t6b, teast, east, sp, mi


def takeaway_se5b(grid, man_meta):
    """Boise as the stand-in for Central/Eastern Oregon and SE Washington."""
    S = {k: merged_stats(grid, man_meta, k) for k in grid["stats"]}
    bo, rd, ya = (S["boise-ap-gowen-field-angb"], S["redmond-muni-ap-roberts-field"],
                  S["yakima-af-mcallister-field"])
    sp = S["spokane-intl-ap"]
    return (f"Boise is a close match for Yakima: HDD65 within {abs(pct_diff(ya['hdd'], bo['hdd'])):.0f}%, "
            f"CDD65 {ya['cdd']:,} vs {bo['cdd']:,}, the same {t(bo['p10'])} cold-10% threshold. "
            f"Redmond heats like Boise ({pct_diff(rd['hdd'], bo['hdd']):+.0f}% HDD65) but cools far less: "
            f"{rd['cdd']:,} CDD65 ({pct_diff(rd['cdd'], bo['cdd']):.0f}%), hottest 10% starting "
            f"{bo['p90'] - rd['p90']:.0f}°F lower — on cooling it looks more like Spokane ({sp['cdd']:,}).")


def add_east_points(slide, east, sp, mi, bottom_line):
    """Bottom line and bullets under the two-row Spokane/Missoula grid."""
    y = Inches(5.22)
    rich_box(slide, Inches(0.60), y, Inches(11.4), Inches(1.6), [
        [("Bottom line: ", 11.5, True, B.BRAND_INK), (bottom_line, 11.5, False, B.BRAND_INK)],
        [("Heating energy: ", 10.5, True, B.BRAND_INK),
         (f"expect a clear step up from Spokane to Missoula — {east['hdd']:.0f}% more HDD65, colder "
          f"through the whole distribution (coldest 10% threshold {east['p10']:.0f}°F lower, 99.6% "
          f"design {east['design']:.0f}°F lower).", 10.5, False, SOFT)],
        [("Cooling energy: ", 10.5, True, B.BRAND_INK),
         (f"the two will look alike — CDD65 differs by {abs(mi['cdd'] - sp['cdd']):,} °F·day and "
          f"peak summer temperatures by a few degrees.", 10.5, False, SOFT)],
        [("Caveat: ", 10.5, True, B.BRAND_INK),
         ("by station data (ASHRAE 2025) these two files classify as 5A and 6A (moist) rather "
          "than the code's 5B and 6B; that does not change the heating gap between them.",
          10.5, False, SOFT)],
    ])


def add_methods_slide(prs, grid):
    cfg = grid["config"]
    slide = prs.slides.add_slide(B.layout(prs, B.L_TITLE_ONLY))
    B.set_text(slide, 0, "Data and Methods")
    utci = ("Extreme cold < −40°C · Very strong cold −40 to −27 · Strong cold −27 to −13 · "
            "Moderate cold −13 to 0 · Slight cold 0 to 9 · No thermal stress 9 to 26 "
            "(cool 9–18, comfort 18–26) · Moderate heat 26 to 32 · Strong heat 32 to 38 · "
            "Very strong heat 38 to 46 · Extreme heat > 46 (UTCI, °C)")
    paras = [
        [("Weather files. ", 11, True, B.BRAND_INK),
         ("OneBuilding TMYx 2011–2025 typical meteorological years, one per airport station "
          "(8,760 hours each). ASHRAE design temperatures and station climate zones are read from "
          "each file's companion .stat (2025 ASHRAE Handbook — Fundamentals, Ch. 14).",
          11, False, SOFT)],
        [("Climate zones. ", 11, True, B.BRAND_INK),
         ("Rows and colours use the code (county) zone from NEEA's selection table. The station "
          "zone computed from recent climate normals can differ: Boise 4B, Spokane 5A, Redmond 5C, "
          "Missoula 6A. "
          "DOE/PNNL reference cities are the ASHRAE 90.1 prototype-model locations "
          "(4C Seattle, 5B Denver, 6B Great Falls).", 11, False, SOFT)],
        [("Degree days. ", 11, True, B.BRAND_INK),
         (f"Hourly: Σ max(0, {cfg.get('hBase', 65)}°F − T)/24 for heating and Σ max(0, T − "
          f"{cfg.get('cBase', 65)}°F)/24 for cooling, all hours. Appendix slides also show the "
          "occupied 7:00–19:00 subset.", 11, False, SOFT)],
        [("Temperature extremes. ", 11, True, B.BRAND_INK),
         ("Coldest/hottest hour of the file; the 10% and 90% thresholds are percentiles of all "
          "hourly dry-bulb values (the temperature the coldest / hottest 10% of hours fall beyond).",
          11, False, SOFT)],
        [("Outdoor comfort. ", 11, True, B.BRAND_INK),
         ("Universal Thermal Climate Index per hour from dry bulb, humidity, wind and direct sun "
          "(no shading or wind block — the dashboard's base case). Categories: " + utci + ".",
          11, False, SOFT)],
        [("Shared scales. ", 11, True, B.BRAND_INK),
         ("Every comparison chart uses one scale across all locations in the deck, so panels can be read "
          "against each other across slides.", 11, False, SOFT)],
    ]
    rich_box(slide, Inches(0.94), Inches(1.15), Inches(11.4), Inches(5.6), paras)
    return slide


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="out/lllc/grid/grid.json")
    ap.add_argument("--manifest", default="out/lllc/manifest.json")
    ap.add_argument("--template", default=str(B.DEFAULT_TEMPLATE))
    ap.add_argument("--out", default="out/lllc/LLLC-weather-deck.pptx")
    args = ap.parse_args()

    grid = json.loads(B.resolve(args.grid).read_text(encoding="utf-8"))
    manifest = json.loads(B.resolve(args.manifest).read_text(encoding="utf-8"))
    man_locs = {l["slug"]: l for l in manifest["locations"]}
    man_meta = {k: v.get("meta", {}) for k, v in man_locs.items()}
    cfg = grid["config"]
    missing = [l["slug"] for l in cfg["locations"] if l["slug"] not in man_locs]
    if missing:
        sys.exit("manifest is missing: " + ", ".join(missing) + " -- run render.mjs first")

    prs = B.Presentation(str(B.resolve(args.template)))
    B.drop_existing_slides(prs)

    B.add_title_slide(prs, cfg.get("title", "Weather Locations"), cfg.get("client", ""),
                      "Weather File Review")
    add_map_slide(prs, grid, man_meta)
    add_numbers_slide(prs, grid, man_meta)

    t5b, t4c, t6b, teast, east, sp, mi = takeaways(grid, man_meta)

    section_slide(prs, "5B: Boise and Spokane",
                  "Two 5B simulations: Boise, ID (highest CDD in the set) and Spokane, WA. Shown "
                  "against Denver, CO (DOE/PNNL 5B city); whether Boise stands in for Central/Eastern "
                  "Oregon and SE Washington; and whether Spokane and Missoula are far enough apart.")
    add_grid_slide(prs, grid, man_meta, "5B: Boise vs. Spokane vs. Denver",
                   "The two modeled 5B cities and the DOE/PNNL 5B city · shared scales",
                   ["boise-ap-gowen-field-angb", "spokane-intl-ap", "denver-intl-ap"], t5b)
    add_grid_slide(prs, grid, man_meta, "5B: Boise vs. Redmond vs. Yakima",
                   "Does Boise represent Central/Eastern Oregon and SE Washington "
                   "(gas funder service area)? · shared scales",
                   ["boise-ap-gowen-field-angb", "redmond-muni-ap-roberts-field",
                    "yakima-af-mcallister-field"], takeaway_se5b(grid, man_meta))
    s = add_grid_slide(prs, grid, man_meta, "Are Spokane and Missoula Different Enough?",
                       "Proposed 5B and 6B locations side by side · same scales as every other grid",
                       ["spokane-intl-ap", "missoula-intl-ap"], None)
    add_east_points(s, east, sp, mi, teast)

    section_slide(prs, "Reference: Each Zone vs. DOE/PNNL and NEEA Cities",
                  "Each modeled location against the DOE/PNNL prototype city for its zone and "
                  "populated NEEA cities. 5B is covered in the previous section.")
    add_grid_slide(prs, grid, man_meta, "4C: Seattle vs. Portland vs. Eugene",
                   "Seattle is both the proposed location and the DOE/PNNL 4C city · shared scales",
                   ["seattle-tacoma-intl-ap", "portland-intl-ap", "eugene-ap-sweet-field"], t4c)
    add_grid_slide(prs, grid, man_meta, "6B: Missoula vs. Great Falls vs. Helena",
                   "Proposed location, the DOE/PNNL 6B city and the prior A2 candidate · shared scales",
                   ["missoula-intl-ap", "great-falls", "helena-rgnl-ap"], t6b)

    section_slide(prs, "Appendix: Location Backup",
                  "Two slides per location: station, climate class and annual temperature; "
                  "degree days by temperature bin and by month (occupied hours over all hours).")
    for l in cfg["locations"]:
        loc = man_locs[l["slug"]]
        B.add_location_slide(prs, loc)
        B.add_degree_day_slide(prs, loc)
    add_methods_slide(prs, grid)

    out = B.resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    print(f"wrote {B.show(out)}  ({len(prs.slides._sldIdLst)} slides)")


if __name__ == "__main__":
    main()
