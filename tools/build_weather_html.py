#!/usr/bin/env python3
"""
Interactive single-file HTML version of the LLLC weather deck.

    python tools/build_weather_html.py
    python tools/build_weather_html.py --out out/lllc/LLLC-weather-locations.html

Same inputs as build_weather_deck.py (out/lllc/grid/grid.json and
out/lllc/manifest.json) and the same takeaway functions, so every number
matches the slides. Cities can be toggled on and off; every section follows
the selection. Chart PNGs are downscaled and embedded once as data URIs, and
the map is the vector SVG from render_grid.mjs, so the file needs nothing
beside it. Needs Pillow.
"""
import argparse
import base64
import html
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_weather_deck as W  # noqa: E402
import build_pptx as B  # noqa: E402

from PIL import Image  # noqa: E402

ZONES = ["4C", "5B", "6B"]


def img_uri(rel, max_w):
    im = Image.open(B.resolve(rel)).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def e(s):
    return html.escape(str(s))


def build(grid, manifest):
    cfg = grid["config"]
    man_locs = {l["slug"]: l for l in manifest["locations"]}
    man_meta = {k: v.get("meta", {}) for k, v in man_locs.items()}
    charts = grid["charts"]

    t5b, t4c, t6b, teast, east, sp, mi = W.takeaways(grid, man_meta)
    tse = W.takeaway_se5b(grid, man_meta)
    S = {k: W.merged_stats(grid, man_meta, k) for k in grid["stats"]}

    cities = []
    for l in cfg["locations"]:
        slug = l["slug"]
        m, s = man_locs[slug], S[slug]
        meta, ch = m.get("meta", {}), m.get("charts", {})
        cities.append({
            "slug": slug, "city": l["city"], "short": l["short"], "zone": l["codeZone"],
            "role": l["role"], "roleKind": l["roleKind"], "modeled": bool(l.get("modeled")),
            "station": meta.get("station", ""), "stationZone": meta.get("ashraeZoneCode", ""),
            "facts": " · ".join(x for x in [meta.get("subtitle", ""), meta.get("elevation", ""),
                                             f"ASHRAE {meta.get('ashraeZone', '')}",
                                             f"Köppen {meta.get('koppenCode', '')}"] if x.strip()),
            "stats": {k: s.get(k) for k in ("hdd", "cdd", "min", "p10", "p50", "p90", "max",
                                            "designHeating996", "designCooling04",
                                            "utciNoStressPct", "elevationFt")},
            "img": {
                "utci": img_uri(charts[f"grid-utci-{slug}"], 800),
                "dd": img_uri(charts[f"grid-dd-{slug}"], 800),
                "temp": img_uri(charts[f"grid-temp-{slug}"], 800),
                "annual": img_uri(ch["temperature-annual"], 1600) if "temperature-annual" in ch else None,
                "ddm": img_uri(ch["degree-days-monthly"], 1600) if "degree-days-monthly" in ch else None,
                "profile": img_uri(ch["temperature-daily-profile"], 1600) if "temperature-daily-profile" in ch else None,
                "ddt": img_uri(ch["degree-days-by-temperature"], 1600) if "degree-days-by-temperature" in ch else None,
                "locmap": img_uri(ch["location-map"], 900) if "location-map" in ch else None,
                "ucat": img_uri(ch["utci-categories"], 900) if "utci-categories" in ch else None,
            },
            # Everything the two per-location backup slides print as text.
            "meta": {k: meta.get(k, "") for k in ("subtitle", "latitude", "longitude", "elevation",
                                                   "timezone", "stateName", "ashraeZone",
                                                   "koppenCode", "koppenName", "koppenDescription")},
            "totals": {k: m.get("totals", {}).get(k) for k in ("hddOccupied", "hddAll", "cddOccupied",
                                                               "cddAll", "unit", "hBase", "cBase",
                                                               "occStart", "occEnd", "occupiedHours",
                                                               "totalHours")},
        })

    presets = [
        {"id": "all", "label": "All cities", "scope": "top", "slugs": [c["slug"] for c in cities]},
        {"id": "modeled", "label": "Modeled cities", "scope": "top",
         "slugs": [c["slug"] for c in cities if c["modeled"]]},
        {"id": "5b-doe", "scope": "cmp", "label": "Boise · Spokane · Denver",
         "slugs": ["boise-ap-gowen-field-angb", "spokane-intl-ap", "denver-intl-ap"], "note": t5b},
        {"id": "5b-pair", "scope": "cmp", "label": "Boise vs. Spokane",
         "slugs": ["boise-ap-gowen-field-angb", "spokane-intl-ap"]},
        {"id": "5b-se", "scope": "cmp", "label": "Boise · Redmond · Yakima",
         "slugs": ["boise-ap-gowen-field-angb", "redmond-muni-ap-roberts-field",
                   "yakima-af-mcallister-field"], "note": tse},
        {"id": "east", "scope": "cmp", "label": "Spokane vs. Missoula",
         "slugs": ["spokane-intl-ap", "missoula-intl-ap"],
         "note": "Bottom line: " + teast + f" Heating: coldest 10% threshold {east['p10']:.0f}°F lower and "
                 f"99.6% design {east['design']:.0f}°F lower in Missoula. Cooling: CDD65 differs by "
                 f"{abs(mi['cdd'] - sp['cdd']):,} °F·day."},
        {"id": "doe", "label": "DOE/PNNL cities", "scope": "top",
         "slugs": ["seattle-tacoma-intl-ap", "denver-intl-ap", "great-falls"]},
    ]

    metrics = [{"label": lab, "key": key} for lab, key, _ in W.METRICS]
    # Formatting kind per metric, applied in the page.
    kinds = {"hdd": "int", "cdd": "int", "utciNoStressPct": "pct", "elevationFt": "ft",
             "stationZone": "text"}
    for mtr in metrics:
        mtr["kind"] = kinds.get(mtr["key"], "temp")

    zone_notes = {"4C": [t4c], "5B": [t5b, tse], "6B": [t6b]}
    zone_subs = {
        "4C": "Seattle is both the proposed location and the DOE/PNNL 4C city · Portland and Eugene are populated NEEA cities",
        "5B": "Boise and Spokane (both modeled), the DOE/PNNL city Denver, and Redmond and Yakima for the SE 5B gas funder area",
        "6B": "Missoula (proposed), Great Falls (DOE/PNNL 6B city) and Helena (prior A2 candidate)",
    }
    findings = [
        ("5B (Boise + Spokane):", t5b), ("SE 5B (Redmond, Yakima):", tse),
        ("Spokane vs. Missoula:", teast), ("4C:", t4c), ("6B:", t6b),
    ]

    data = {
        "cities": cities, "presets": presets, "metrics": metrics,
        "zoneColors": cfg["zoneColors"], "zoneNotes": zone_notes, "zoneSubs": zone_subs,
    }
    map_svg = B.resolve(charts["grid-map-svg"]).read_text(encoding="utf-8")
    findings_html = "".join(f"<li><b>{e(a)}</b> {e(b)}</li>" for a, b in findings)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    return (TEMPLATE
            .replace("%%TITLE%%", e(cfg.get("title", "Weather Locations")))
            .replace("%%CLIENT%%", e(cfg.get("client", "")))
            .replace("%%DATE%%", f"{date.today():%B} {date.today().day}, {date.today().year}")
            .replace("%%FINDINGS%%", findings_html)
            .replace("%%MAP%%", map_svg)
            .replace("%%DATA%%", payload))


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLLC Weather Locations</title>
<style>
:root { --ink:#1a1f16; --soft:#4a5245; --muted:#7a8075; --line:#e6e8e1; --bg:#f4f5f0; --card:#fff;
        --orange:#ff6600; --teal:#00a3b4; --hdd:#ff6600; --cdd:#00a3b4; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.5 "Open Sans", "Segoe UI", Helvetica, Arial, sans-serif; }
header { background:var(--ink); color:#fff; padding:30px 16px 26px; }
.wrap { max-width:1240px; margin:0 auto; }
header .eyebrow { color:var(--orange); letter-spacing:.12em; text-transform:uppercase; font-size:12px; font-weight:700; }
header h1 { font:700 34px/1.15 "DM Sans", "Open Sans", sans-serif; margin:6px 0 4px; }
header p { margin:0; color:#c9cdc4; }
.bar { position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid var(--line);
       box-shadow:0 2px 6px rgba(26,31,22,.06); }
.bar .wrap { padding:10px 16px; }
.picker { display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; }
.zgrp { display:flex; flex-wrap:wrap; gap:5px; align-items:center; }
.zlab { font-size:12px; font-weight:700; color:#fff; border-radius:4px; padding:3px 7px; cursor:pointer; border:0; }
.chip { font:13px "Open Sans", sans-serif; border:1.5px solid var(--zc); color:var(--zc); background:#fff;
        border-radius:16px; padding:3px 10px; cursor:pointer; }
.chip[aria-pressed="true"] { background:var(--zc); color:#fff; }
.chip:focus-visible, .zlab:focus-visible, .pbtn:focus-visible { outline:2px solid var(--ink); outline-offset:2px; }
.presets { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:8px; font-size:13px; color:var(--muted); }
.pbtn { font:12.5px "Open Sans", sans-serif; border:1px solid var(--line); background:var(--bg); color:var(--soft);
        border-radius:14px; padding:3px 10px; cursor:pointer; }
.pbtn.on { border-color:var(--ink); color:var(--ink); font-weight:600; }
.count { margin-left:auto; color:var(--muted); font-size:13px; }
nav.toc { display:flex; gap:16px; overflow-x:auto; padding:8px 16px 0; max-width:1240px; margin:0 auto; }
nav.toc a { color:var(--soft); text-decoration:none; white-space:nowrap; font-size:13.5px; }
nav.toc a:hover { color:var(--orange); }
main { padding:12px 16px 60px; }
h2 { font:700 24px/1.2 "DM Sans", "Open Sans", sans-serif; margin:34px 0 10px; scroll-margin-top:120px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px; margin:0 0 18px; }
.sub, .muted { color:var(--muted); } .sub { margin:0 0 14px; }
.small { font-size:13px; color:var(--soft); }
.findings ul { margin:0; padding-left:20px; } .findings li { margin:6px 0; }
.maprow { display:grid; grid-template-columns: 1.25fr 1fr; gap:24px; align-items:start; }
.maprow svg { width:100%; height:auto; border-radius:6px; }
.maprow svg g.site { transition:opacity .2s; } .maprow svg g.site.off { opacity:.12; }
.zones { list-style:none; padding:0; margin:0; } .zones li { display:flex; gap:12px; margin:0 0 14px; }
.zchip { color:#fff; font-weight:700; border-radius:6px; padding:5px 9px; height:fit-content; }
.key { font-size:13px; color:var(--soft); border-top:1px solid var(--line); padding-top:10px; }
.tablewrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { padding:7px 8px; text-align:center; border-bottom:1px solid var(--line); }
#numbers tbody th { text-align:left; font-weight:400; color:var(--soft); position:sticky; left:0; background:#fff; min-width:210px; }
#numbers tbody tr:nth-child(odd) td, #numbers tbody tr:nth-child(odd) th { background:#f8f9f5; }
thead th { background:var(--bg); } th.zh { color:#fff; } .b { font-weight:700; }
.heads, .row { display:grid; grid-template-columns: 170px repeat(3, 1fr); gap:10px; align-items:center; }
.heads { align-items:end; margin-bottom:4px; }
.heads b { display:block; } .heads span { display:block; font-size:12px; color:var(--muted); line-height:1.35; }
.row { padding:6px 0; border-top:1px solid var(--line); }
.row img { width:100%; height:auto; display:block; }
.rowlab { border-left:5px solid var(--zc); padding-left:10px; }
.rowlab h4 { margin:0; font-size:16px; } .rowlab p { margin:2px 0 0; font-size:12.5px; }
.role { color:var(--zc); } .role.prop { font-weight:700; } .zone { color:var(--muted); }
.take { font-style:italic; margin:12px 0 0; padding:10px 12px; background:var(--bg); border-radius:6px; }
.empty { color:var(--muted); font-style:italic; padding:12px 0; }
.maprow > *, .row > * { min-width:0; }
.ctrl { font-size:13.5px; color:var(--soft); margin-bottom:10px; }
.ctrl select { font:13.5px "Open Sans", sans-serif; padding:3px 6px; border:1px solid var(--line); border-radius:6px; }
.cmpbox { border-top:1px solid var(--line); margin-top:14px; padding-top:16px; }
.cmpbox h3 { font:700 21px/1.25 "DM Sans", "Open Sans", sans-serif; margin:0 0 2px; }
.pts { margin:12px 0 0; padding-left:20px; } .pts li { margin:5px 0; }
#cmppicker .chip { font-size:12.5px; }
details { background:#fff; border:1px solid var(--line); border-radius:8px; margin:0 0 8px; padding:0 14px; }
summary { cursor:pointer; padding:12px 0; font-weight:600; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
summary .num { margin-left:auto; font-weight:400; color:var(--soft); font-size:13px; }
.dot { width:12px; height:12px; border-radius:50%; display:inline-block; }
details figure { margin:0 0 14px; } details img { width:100%; height:auto; display:block; }
.bk { border-top:1px solid var(--line); padding:16px 0 10px; }
.bkt { font:700 20px/1.2 "DM Sans", "Open Sans", sans-serif; margin:0 0 10px; }
.bk1 { display:grid; grid-template-columns: 300px 1fr; gap:24px; align-items:start; }
.bk2 { display:grid; grid-template-columns: 1fr 260px; gap:24px; align-items:start; }
.bk1 > *, .bk2 > * { min-width:0; }
.facts { list-style:none; padding:0; margin:4px 0 12px; font-size:14px; } .facts li { margin:1px 0; }
.zonehd { font-weight:700; font-size:17px; margin:0; }
.callouts .co { margin:0 0 22px; font-size:14px; }
.callouts .big { font:700 36px/1.1 "Open Sans", sans-serif; }
.note { font-style:italic; font-size:14px; margin:4px 0 0; }
figcaption { font-size:12.5px; color:var(--muted); }
.methods p { margin:0 0 10px; }
footer { color:var(--muted); font-size:12.5px; max-width:1240px; margin:0 auto; padding:0 16px 30px; }
[hidden] { display:none !important; }
@media (max-width: 860px) {
  .maprow, .bk1, .bk2 { grid-template-columns: 1fr; }
  .bar { position:static; }
  .heads { display:none; }
  .row { grid-template-columns: 1fr; }
  header h1 { font-size:27px; }
  .count { margin-left:0; width:100%; }
}
</style></head>
<body>
<header><div class="wrap">
  <div class="eyebrow">Weather File Review</div>
  <h1>%%TITLE%%</h1>
  <p>%%CLIENT%% · A2 Efficiency · %%DATE%%</p>
</div></header>

<div class="bar">
  <div class="wrap">
    <div class="picker" id="picker"></div>
    <div class="presets" id="presets"><span>Show:</span></div>
  </div>
  <nav class="toc">
    <a href="#findings">Key findings</a><a href="#locations">Locations</a><a href="#numbers-h">Numbers</a>
    <a href="#z-4C">4C</a><a href="#z-5B">5B</a><a href="#z-6B">6B</a>
    <a href="#sbs">Side by side</a><a href="#backup">Backup</a><a href="#methods">Methods</a>
  </nav>
</div>

<main class="wrap">

<h2 id="findings">Key findings</h2>
<section class="card findings"><ul>%%FINDINGS%%</ul></section>

<h2 id="locations">Locations in the analysis</h2>
<section class="card maprow">
  <div id="map">%%MAP%%</div>
  <div>
    <ul class="zones" id="zonelist"></ul>
    <p class="small"><b>5C (Port Angeles)</b> is not modeled: NEEA chose 4C and 5B for Washington code savings; 5C is too small.</p>
    <div class="key">● filled = proposed modeling location &nbsp; ◆ = DOE/PNNL prototype city &nbsp; ○ = comparison city
      <br>Colour = code climate zone · shaded states = NEEA region · cities you turn off fade on the map</div>
  </div>
</section>

<h2 id="numbers-h">Locations in numbers</h2>
<section class="card">
  <p class="sub">Modeled locations in bold · all 8,760 hours of the typical year</p>
  <div class="tablewrap"><table id="numbers"><thead></thead><tbody></tbody></table></div>
  <p class="small">Code zones are county assignments. The station-level zone from the 2025 ASHRAE Handbook data (last row)
    differs for Boise, Spokane, Redmond and Missoula.</p>
</section>

<div id="zones"></div>

<h2 id="sbs">Locations side by side</h2>
<section class="card">
  <div class="ctrl"><b>Choose two or more cities to compare</b> <span class="muted">· independent of the city bar at the top</span></div>
  <div class="picker" id="cmppicker"></div>
  <div class="presets" id="cmppresets"><span>Quick comparisons:</span></div>
  <div class="ctrl" style="margin-top:10px"><label>Compare against <select id="ref"></select></label></div>
  <div class="cmpbox">
    <h3 id="cmptitle"></h3>
    <p class="sub" id="cmpsub"></p>
    <div id="cmpgrid"></div>
    <p class="take" id="cmpbottom"></p>
    <ul class="pts" id="cmppts"></ul>
  </div>
</section>

<h2 id="backup">Location backup</h2>
<p class="sub">The two backup slides for each station — location and degree days. Click a city to expand.</p>
<div id="backuplist"></div>

<h2 id="methods">Data and methods</h2>
<section class="card methods">
  <p><b>Weather files.</b> OneBuilding TMYx 2011–2025 typical meteorological years, one per airport station (8,760 hours each).
    ASHRAE design temperatures and station climate zones come from each file's companion .stat (2025 ASHRAE Handbook — Fundamentals, Ch. 14).</p>
  <p><b>Climate zones.</b> Sections and colours use the code (county) zone from NEEA's selection table. The station zone computed from recent
    climate normals can differ: Boise 4B, Spokane 5A, Redmond 5C, Missoula 6A. DOE/PNNL reference cities are the ASHRAE 90.1 prototype-model
    locations (4C Seattle, 5B Denver, 6B Great Falls).</p>
  <p><b>Degree days.</b> Hourly: Σ max(0, 65°F − T)/24 for heating and Σ max(0, T − 65°F)/24 for cooling, all hours.
    The backup charts also show the occupied 7:00–19:00 subset.</p>
  <p><b>Temperature extremes.</b> Coldest/hottest hour of the file; the 10% and 90% thresholds are percentiles of all hourly dry-bulb values.</p>
  <p><b>Outdoor comfort.</b> Universal Thermal Climate Index per hour from dry bulb, humidity, wind and direct sun, with no shading or wind block.</p>
  <p><b>Shared scales.</b> Every comparison chart uses one scale across all locations, so any two rows can be read against each other.</p>
</section>
</main>
<footer>Station list per NEEA (K. Bae, 10/29/2026; approved 10/30). Redmond and Yakima added 11/2/2026 at NEEA's request.
  Same data and charts as the LLLC weather deck.</footer>

<script id="data" type="application/json">%%DATA%%</script>
<script>
(function () {
  'use strict';
  var D = JSON.parse(document.getElementById('data').textContent);
  var C = D.cities, BY = {}, ZC = D.zoneColors, ZONES = ['4C', '5B', '6B'];
  C.forEach(function (c) { BY[c.slug] = c; });
  var sel = {};
  C.forEach(function (c) { sel[c.slug] = true; });

  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) {
      if (k === 'style') n.style.cssText = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    if (html !== undefined) n.innerHTML = html;
    return n;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (m) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]; }); }
  function T(v) { if (v === null || v === undefined) return '—'; var r = Math.round(v); return (r < 0 ? '−' : '') + Math.abs(r) + '°F'; }
  function fmt(v, kind) {
    if (v === null || v === undefined || v === '') return '—';
    if (kind === 'int') return Math.round(v).toLocaleString('en-US');
    if (kind === 'pct') return Math.round(v) + '%';
    if (kind === 'ft') return Math.round(v).toLocaleString('en-US') + ' ft';
    if (kind === 'text') return String(v);
    return T(v);
  }
  function chosen() { return C.filter(function (c) { return sel[c.slug]; }); }

  // ---------- pickers ----------
  // Two independent selections: `sel` drives every section; `cmp` drives
  // only the side-by-side comparison.
  var cmp = {}; ['spokane-intl-ap', 'missoula-intl-ap'].forEach(function (k) { cmp[k] = true; });
  function buildPicker(box, state, onChange, withCount) {
    ZONES.forEach(function (z) {
      var g = el('div', { 'class': 'zgrp' });
      var zl = el('button', { 'class': 'zlab', style: 'background:' + ZC[z], title: 'Toggle all ' + z + ' cities', type: 'button' }, z);
      zl.onclick = function () {
        var zs = C.filter(function (c) { return c.zone === z; });
        var allOn = zs.every(function (c) { return state[c.slug]; });
        zs.forEach(function (c) { state[c.slug] = !allOn; });
        onChange();
      };
      g.appendChild(zl);
      C.filter(function (c) { return c.zone === z; }).forEach(function (c) {
        var b = el('button', { 'class': 'chip', type: 'button', 'data-slug': c.slug, style: '--zc:' + ZC[z], 'aria-pressed': 'false' }, esc(c.short));
        b.onclick = function () { state[c.slug] = !state[c.slug]; onChange(); };
        g.appendChild(b);
      });
      box.appendChild(g);
    });
    if (withCount) box.appendChild(el('span', { 'class': 'count', id: 'count' }));
  }
  function buildPresets(box, scope, state, onChange) {
    D.presets.filter(function (p) { return p.scope === scope; }).forEach(function (p) {
      var b = el('button', { 'class': 'pbtn', type: 'button', 'data-id': p.id }, esc(p.label));
      b.onclick = function () { C.forEach(function (c) { state[c.slug] = p.slugs.indexOf(c.slug) >= 0; }); onChange(); };
      box.appendChild(b);
    });
  }
  function syncPicker(box, state) {
    box.querySelectorAll('.chip').forEach(function (b) { b.setAttribute('aria-pressed', state[b.getAttribute('data-slug')] ? 'true' : 'false'); });
  }
  function syncPresets(box, state) {
    var ids = C.filter(function (c) { return state[c.slug]; }).map(function (c) { return c.slug; }).sort().join();
    box.querySelectorAll('.pbtn').forEach(function (b) {
      var p = D.presets.filter(function (q) { return q.id === b.getAttribute('data-id'); })[0];
      b.classList.toggle('on', p.slugs.slice().sort().join() === ids);
    });
  }
  buildPicker(document.getElementById('picker'), sel, function () { update(); }, true);
  buildPresets(document.getElementById('presets'), 'top', sel, function () { update(); });
  buildPicker(document.getElementById('cmppicker'), cmp, function () { renderCmp(); }, false);
  buildPresets(document.getElementById('cmppresets'), 'cmp', cmp, function () { renderCmp(); });

  // ---------- zone list beside the map ----------
  var zoneNote = { '4C': 'Seattle is also the DOE/PNNL 4C city', '5B': 'Two 5B runs; Boise has the highest CDD',
                   '6B': 'In place of Helena, MT' };
  var zl = document.getElementById('zonelist');
  ZONES.forEach(function (z) {
    var mod = C.filter(function (c) { return c.zone === z && c.modeled; });
    var refs = C.filter(function (c) { return c.zone === z && !c.modeled; })
      .map(function (c) { return esc(c.city) + ' (' + (c.roleKind === 'doe' ? 'DOE/PNNL' : 'NEEA') + ')'; }).join('; ');
    zl.appendChild(el('li', {}, '<span class="zchip" style="background:' + ZC[z] + '">' + z + '</span><div><b>' +
      mod.map(function (c) { return esc(c.city); }).join(' + ') + '</b> <span class="muted">' + esc(zoneNote[z]) +
      '</span><br><span class="small">Compared with: ' + refs + '</span></div>'));
  });

  // ---------- chart rows ----------
  var HEADS = '<div class="heads"><div></div>' +
    '<div><b>Outdoor thermal comfort (UTCI)</b><span>% of hours in each stress category, cold → hot</span></div>' +
    '<div><b>Heating &amp; cooling degree days</b><span>Monthly °F·day, base 65°F, all hours</span></div>' +
    '<div><b>Temperature extremes</b><span>Month min–max (thin), middle 80% (box), median (line); dashed = coldest / hottest 10% of the year</span></div></div>';
  function rowHtml(c) {
    var zn = 'Code zone ' + c.zone + (c.stationZone && c.stationZone !== c.zone ? ' · station data ' + c.stationZone : '');
    return '<div class="row" data-slug="' + c.slug + '" style="--zc:' + ZC[c.zone] + '"><div class="rowlab"><h4>' + esc(c.city) +
      '</h4><p class="role' + (c.roleKind === 'proposed' ? ' prop' : '') + '">' + esc(c.role) + '</p><p class="zone">' + esc(zn) + '</p></div>' +
      ['utci', 'dd', 'temp'].map(function (k) { return '<img alt="' + esc(c.city) + ' ' + k + '" src="' + c.img[k] + '">'; }).join('') + '</div>';
  }

  var zonesBox = document.getElementById('zones');
  ZONES.forEach(function (z) {
    var sec = el('div');
    sec.appendChild(el('h2', { id: 'z-' + z }, z + ' locations'));
    var card = el('section', { 'class': 'card' });
    card.appendChild(el('p', { 'class': 'sub' }, esc(D.zoneSubs[z]) + ' · shared scales'));
    card.insertAdjacentHTML('beforeend', HEADS);
    C.filter(function (c) { return c.zone === z; }).forEach(function (c) { card.insertAdjacentHTML('beforeend', rowHtml(c)); });
    card.appendChild(el('p', { 'class': 'empty', 'data-empty': z, hidden: '' }, 'No ' + z + ' cities selected — turn one on in the bar above.'));
    (D.zoneNotes[z] || []).forEach(function (t) { card.appendChild(el('p', { 'class': 'take' }, esc(t))); });
    sec.appendChild(card);
    zonesBox.appendChild(sec);
  });

  // ---------- backup: the two per-location slides, as two panels ----------
  function clock(h) { h = +h; var ap = h < 12 ? 'am' : 'pm', d = h % 12 || 12; return d + ap; }
  function fig(c, key, cap) {
    return c.img[key] ? '<figure><img alt="' + esc(c.city + ' — ' + cap) + '" data-src="' + key + '">' +
      (cap ? '<figcaption>' + esc(cap) + '</figcaption>' : '') + '</figure>' : '';
  }
  var bl = document.getElementById('backuplist');
  C.forEach(function (c) {
    var d = el('details', { 'data-slug': c.slug }), m = c.meta, t = c.totals;
    var facts = [['Latitude', m.latitude], ['Longitude', m.longitude], ['Elevation', m.elevation],
                 ['Time zone', m.timezone], ['State', m.stateName]]
      .filter(function (f) { return f[1]; })
      .map(function (f) { return '<li>' + f[0] + ': ' + esc(f[1]) + '</li>'; }).join('');
    var kop = m.koppenCode ? 'Köppen ' + esc(m.koppenCode) + (m.koppenName ? ' — ' + esc(m.koppenName) : '') : '';
    var pct = t.totalHours ? Math.round(t.occupiedHours / t.totalHours * 100) : 0;
    var panel1 =
      '<div class="bk"><h4 class="bkt">' + esc(c.station) + '</h4><div class="bk1">' +
        '<div class="bkl"><p class="small">' + esc(m.subtitle) + '</p><ul class="facts">' + facts + '</ul>' +
          '<p class="zonehd">ASHRAE ' + esc(m.ashraeZone) + '</p><p class="small">' + kop +
          (m.koppenDescription ? '<br>' + esc(m.koppenDescription) : '') + '</p>' +
          fig(c, 'locmap', '') + fig(c, 'ucat', 'Outdoor comfort — UTCI hours by stress category') + '</div>' +
        '<div class="bkr">' + fig(c, 'annual', 'Daily minimum, mean and maximum across the year') +
          fig(c, 'profile', 'Hourly dry bulb and dew point by month (range and mean)') + '</div>' +
      '</div></div>';
    var panel2 = !t.unit ? '' :
      '<div class="bk"><h4 class="bkt">Degree days <span class="muted">· ' + esc(c.station) + '</span></h4><div class="bk2">' +
        '<div class="bkl">' + fig(c, 'ddt', 'Degree days by temperature bin — occupied hours solid, all hours pale') +
          fig(c, 'ddm', 'Degree days by month — occupied hours solid, all hours pale') + '</div>' +
        '<div class="bkr callouts">' +
          '<div class="co"><div class="big" style="color:var(--hdd)">' + fmt(t.hddOccupied, 'int') + '</div>' +
            '<div>heating degree days (' + esc(t.unit) + ', occupied)</div><div class="b">' + fmt(t.hddAll, 'int') + ' all hours</div></div>' +
          '<div class="co"><div class="big" style="color:var(--cdd)">' + fmt(t.cddOccupied, 'int') + '</div>' +
            '<div>cooling degree days (' + esc(t.unit) + ', occupied)</div><div class="b">' + fmt(t.cddAll, 'int') + ' all hours</div></div>' +
          '<div class="co muted"><div class="b">Assumptions</div><div>Base ' + t.hBase + '°F heating and cooling.</div>' +
            '<div>Occupied ' + t.occStart + ':00–' + t.occEnd + ':00, ' + fmt(t.occupiedHours, 'int') + ' of ' +
            fmt(t.totalHours, 'int') + ' h (' + pct + '%).</div></div>' +
        '</div></div>' +
        '<p class="note">Filter shows ' + clock(t.occStart) + ' to ' + clock(t.occEnd) + ' occupied hours and transparent is all data</p>' +
      '</div>';
    d.innerHTML = '<summary><span class="dot" style="background:' + ZC[c.zone] + '"></span>' + esc(c.city) +
      ' <span class="muted">· ' + esc(c.station) + '</span><span class="num">HDD65 ' + fmt(c.stats.hdd, 'int') +
      ' · CDD65 ' + fmt(c.stats.cdd, 'int') + '</span></summary>' + panel1 + panel2;
    // Big images are attached only when opened, which keeps the page quick.
    d.addEventListener('toggle', function () {
      if (!d.open) return;
      d.querySelectorAll('img[data-src]').forEach(function (im) { im.src = c.img[im.getAttribute('data-src')]; im.removeAttribute('data-src'); });
    });
    bl.appendChild(d);
  });

  var ref = document.getElementById('ref');
  var refSlug = 'spokane-intl-ap';

  // ---------- render on every change ----------
  function renderTable() {
    var t = document.getElementById('numbers');
    var cols = chosen();
    var proposed = {}; C.forEach(function (c) { if (c.modeled) proposed[c.slug] = true; });
    var h1 = '<tr><th></th>', h2 = '<tr><th></th>';
    ZONES.forEach(function (z) {
      var n = cols.filter(function (c) { return c.zone === z; }).length;
      if (n) h1 += '<th colspan="' + n + '" class="zh" style="background:' + ZC[z] + '">Climate zone ' + z + '</th>';
    });
    cols.forEach(function (c) { h2 += '<th class="' + (proposed[c.slug] ? 'b' : '') + '">' + esc(c.short) + '</th>'; });
    t.tHead.innerHTML = h1 + '</tr>' + h2 + '</tr>';
    t.tBodies[0].innerHTML = D.metrics.map(function (m) {
      return '<tr><th>' + esc(m.label) + '</th>' + cols.map(function (c) {
        var v = m.key === 'stationZone' ? c.stationZone : c.stats[m.key];
        return '<td class="' + (proposed[c.slug] ? 'b' : '') + '">' + fmt(v, m.kind) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    t.style.minWidth = (230 + cols.length * 86) + 'px';
  }

  // ---------- side by side ----------
  function pct(a, b) { return (a - b) / b * 100; }
  function signed(n, unit) { var r = Math.round(n); return (r > 0 ? '+' : r < 0 ? '−' : '±') + Math.abs(r) + unit; }
  function degWord(d, lo, hi) {
    var r = Math.round(d);
    return r === 0 ? 'the same' : Math.abs(r) + '°F ' + (r < 0 ? (lo || 'lower') : (hi || 'higher'));
  }
  function heatVerdict(d) { d = Math.abs(d); return d < 5 ? 'close' : d < 10 ? 'modestly different' : 'clearly different'; }
  function coolVerdict(d, abs) { d = Math.abs(d); return (abs < 200 || d < 10) ? 'similar' : d < 25 ? 'modestly different' : 'clearly different'; }
  function list(a) { return a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1]; }

  function renderCmp() {
    var cols = C.filter(function (c) { return cmp[c.slug]; });
    syncPicker(document.getElementById('cmppicker'), cmp);
    syncPresets(document.getElementById('cmppresets'), cmp);
    var title = document.getElementById('cmptitle'), sub = document.getElementById('cmpsub'),
        grid = document.getElementById('cmpgrid'), bottom = document.getElementById('cmpbottom'),
        pts = document.getElementById('cmppts');
    if (cols.length && !cmp[refSlug]) refSlug = cols[0].slug;
    ref.innerHTML = cols.map(function (c) { return '<option value="' + c.slug + '"' + (c.slug === refSlug ? ' selected' : '') + '>' + esc(c.city) + '</option>'; }).join('');
    ref.disabled = cols.length < 2;
    if (cols.length < 2) {
      title.textContent = cols.length ? cols[0].city : 'Pick cities to compare';
      sub.textContent = 'Choose at least two cities above.';
      grid.innerHTML = cols.length ? HEADS + cols.map(rowHtml).join('') : '';
      bottom.hidden = true; pts.innerHTML = '';
      return;
    }
    // Reference row first, then the rest in config order.
    var R = BY[refSlug], others = cols.filter(function (c) { return c.slug !== refSlug; });
    var ordered = [R].concat(others);
    title.textContent = ordered.length <= 4 ? ordered.map(function (c) { return c.short; }).join(' vs. ') : 'Comparing ' + ordered.length + ' cities';
    var zs = ZONES.filter(function (z) { return ordered.some(function (c) { return c.zone === z; }); });
    sub.textContent = 'Code zone' + (zs.length > 1 ? 's ' : ' ') + list(zs) + ' · ' + R.short + ' is the reference · same scales as every other grid';
    grid.innerHTML = HEADS + ordered.map(rowHtml).join('');

    var r = R.stats;
    var lines = others.map(function (c) {
      var s = c.stats, dh = pct(s.hdd, r.hdd), dc = pct(s.cdd, r.cdd), ac = Math.abs(s.cdd - r.cdd);
      return { c: c, dh: dh, dc: dc, ac: ac, hv: heatVerdict(dh), cv: coolVerdict(dc, ac),
               med: s.p50 - r.p50, p10: s.p10 - r.p10, p90: s.p90 - r.p90,
               des: (s.designHeating996 === null || r.designHeating996 === null) ? null : s.designHeating996 - r.designHeating996,
               cdes: (s.designCooling04 === null || r.designCooling04 === null) ? null : s.designCooling04 - r.designCooling04 };
    });
    var bl;
    if (lines.length === 1) {
      var L = lines[0], c = L.c, s = c.stats;
      bl = c.short + ' is ' + L.hv + ' for heating and ' + L.cv + ' for cooling: it carries ' + signed(L.dh, '%') + ' HDD65 (' +
           fmt(s.hdd, 'int') + ' vs ' + fmt(r.hdd, 'int') + ') and its median hour is ' + degWord(L.med, 'colder', 'warmer') +
           ', while CDD65 is ' + fmt(s.cdd, 'int') + ' vs ' + fmt(r.cdd, 'int') + ' (' + signed(L.dc, '%') + ').';
    } else {
      bl = 'Against ' + R.short + ': ' + lines.map(function (L) {
        return L.c.short + ' is ' + L.hv + ' for heating (' + signed(L.dh, '%') + ' HDD65) and ' + L.cv + ' for cooling (' + signed(L.dc, '%') + ' CDD65)';
      }).join('; ') + '.';
    }
    bottom.hidden = false;
    bottom.innerHTML = '<b>Bottom line:</b> ' + esc(bl);

    var heat = lines.map(function (L) {
      return (lines.length > 1 ? L.c.short + ' ' : '') + signed(L.dh, '%') + ' HDD65, coldest 10% threshold ' + degWord(L.p10) +
        (L.des === null ? '' : ', 99.6% design ' + degWord(L.des));
    }).join('; ');
    var cool = lines.map(function (L) {
      return (lines.length > 1 ? L.c.short + ' ' : '') + 'CDD65 ' + signed(L.dc, '%') + ' (' + Math.round(L.ac).toLocaleString('en-US') +
        ' °F·day apart), hottest 10% threshold ' + degWord(L.p90) + (L.cdes === null ? '' : ', 0.4% design ' + degWord(L.cdes));
    }).join('; ');
    var items = [
      '<b>Heating energy:</b> compared with ' + esc(R.short) + ' — ' + esc(heat) + '.',
      '<b>Cooling energy:</b> compared with ' + esc(R.short) + ' — ' + esc(cool) + '.'
    ];
    var odd = ordered.filter(function (c) { return c.stationZone && c.stationZone !== c.zone; });
    var cav = [];
    if (zs.length > 1) cav.push('these cities span code zones ' + list(zs));
    if (odd.length) cav.push('by station data (ASHRAE 2025) ' + list(odd.map(function (c) { return c.short + ' reads as ' + c.stationZone; })) +
                             ' rather than ' + (odd.length > 1 ? 'their code zones' : 'its code zone ' + odd[0].zone));
    if (cav.length) items.push('<b>Caveat:</b> ' + esc(cav.join('; ')) + '. The comparison uses the weather files as they are, so it does not change the differences above.');
    pts.innerHTML = items.map(function (t) { return '<li>' + t + '</li>'; }).join('');
  }
  ref.onchange = function () { refSlug = ref.value; renderCmp(); };

  function update() {
    syncPicker(document.getElementById('picker'), sel);
    syncPresets(document.getElementById('presets'), sel);
    document.querySelectorAll('#map g.site').forEach(function (g) { g.classList.toggle('off', !sel[g.getAttribute('data-slug')]); });
    document.querySelectorAll('#zones .row, #backuplist details').forEach(function (n) { n.hidden = !sel[n.getAttribute('data-slug')]; });
    ZONES.forEach(function (z) {
      var any = C.some(function (c) { return c.zone === z && sel[c.slug]; });
      document.querySelector('[data-empty="' + z + '"]').hidden = any;
    });
    var n = chosen().length;
    document.getElementById('count').textContent = n + ' of ' + C.length + ' cities shown';
    renderTable();
  }
  update();
  renderCmp();
})();
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="out/lllc/grid/grid.json")
    ap.add_argument("--manifest", default="out/lllc/manifest.json")
    ap.add_argument("--out", default="out/lllc/LLLC-weather-locations.html")
    a = ap.parse_args()
    grid = json.loads(B.resolve(a.grid).read_text(encoding="utf-8"))
    manifest = json.loads(B.resolve(a.manifest).read_text(encoding="utf-8"))
    out = B.resolve(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(grid, manifest), encoding="utf-8")
    print(f"wrote {B.show(out)}  ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
