# Weather dashboard → PNG → PowerPoint pipeline

Builds a per-location climate deck from EPW weather files. Everything runs from
the command line — no Claude, no editor, no manual steps.

## Quick start

```bash
# one-time setup
cd tools && npm install && npx playwright install chromium && cd ..
pip install python-pptx

# find the exact station names
python tools/make_deck.py --search denver

# build the deck
python tools/make_deck.py "Denver-Centennial AP" "Chicago-OHare" --client "Acme Corp"
```

That writes `out/climate-deck.pptx`. Takes roughly a minute per location, most
of it the UTCI calculation.

Useful flags: `--units SI`, `--hbase 60 --cbase 70`, `--occstart 8 --occend 18`,
`--title`, `--out`, `--skip-fetch` (reuse what is already downloaded),
`--add` (append to the location list rather than replacing it).

## The steps underneath

`make_deck.py` just chains these; run them individually when iterating.

```
tools/fetch_epw.py      station names  ->  weather_files/*.epw + .stat + locations.json
dashboard.html          one EPW        ->  on-screen dashboard (refine charts here)
tools/render.mjs        locations.json ->  out/<slug>/*.png + out/manifest.json
tools/build_pptx.py     manifest       ->  out/climate-deck.pptx
```

`fetch_epw.py`, `make_deck.py` and `topo2geo.py` are stdlib-only; `render.mjs`
needs Playwright and `build_pptx.py` needs python-pptx.

## 1. Choose locations

Resolved against `data/stations.js`, the station index the viewer already ships,
so there is no scraping.

```bash
python tools/fetch_epw.py --search denver          # find the exact name
python tools/fetch_epw.py --clear "Denver-Centennial AP" "Chicago-OHare"
```

`--clear` replaces `tools/locations.json`; without it, entries are appended.
EPWs land in `weather_files/` (gitignored).

## 2. Refine the charts

```bash
python -m http.server 8000
# http://localhost:8000/dashboard.html?epw=weather_files/denver-centennial-ap.epw
```

Query parameters: `epw`, `units` (`IP`|`SI`), `hbase`, `cbase`, `export=1`
(strips the toolbar and card chrome, as the renderer does).

Charts live in `lib/js/epwDashboard.js`. Each is a plain function taking a
container and prepared data, so they can be resized or restyled without
touching the page.

## 3. Render PNGs

```bash
node tools/render.mjs                    # every location
node tools/render.mjs --only denver-centennial-ap
node tools/render.mjs --units SI --scale 2
```

Screenshots every `[data-chart]` element at `--scale` device pixels (default 3,
about 300 DPI for a 10 in placement). Writes `out/<slug>/<chart>.png` and
`out/manifest.json`, which maps each location to its chart files.

Chart names, which become the PNG filenames:

| name | what |
|---|---|
| `location-map` | US locator map, station's state highlighted |
| `temperature-annual` | daily min/mean/max band over the year |
| `temperature-daily-profile` | twelve months in one row, 6a/12p/6p ticks |
| `utci-categories` | UTCI hours per stress category, horizontal bars |
| `degree-days-monthly` | monthly HDD/CDD, occupied over all-hours |
| `degree-days-by-temperature` | HDD/CDD by dry-bulb bin, occupied over all-hours |
| `utci-stress-categories` | UTCI stacked bars, 5 strategy cases (not in the deck) |
| `utci-summary` | UTCI comfort-hours table, 5 strategy cases (not in the deck) |

### Occupied hours

The degree-day charts show occupied hours solid over a pale all-hours bar.
The window defaults to 7:00-19:00 and is set with `--occstart` / `--occend` on
`render.mjs`, or the toolbar inputs on the page.

An EPW hour `h` spans `(h-1):01` to `h:00`, so its midpoint is `h-0.5`; an hour
counts as occupied when that midpoint falls inside the window. 7-19 therefore
selects EPW hours 8..19 — twelve hours a day, 4,380 of 8,760.

## 4. Build the deck

```bash
python tools/build_pptx.py --title "Climate Analysis" --client "Acme Corp"
python tools/build_pptx.py --no-sections --out decks/acme.pptx
```

Slides are created from the template's own layouts, so the master graphics,
theme colours and DM Sans / Open Sans come along untouched. **Two slides per
location:**

1. **Location** — station facts, ASHRAE zone and Köppen class, locator map,
   UTCI hours breakdown, annual temperature, daily profile strip.
2. **Degree days** — occupancy note, degree days by temperature bin and by
   month, headline occupied HDD/CDD figures and the assumptions behind them.

Layouts used, by name — change these constants if the template is revised:

| Constant | Layout |
|---|---|
| `L_TITLE` | `1_Title Slide` |
| `L_BLANK` | `Blank Light` |
| `L_TITLE_ONLY` | `Title Only Light 1` |

The renderer passes `titles=0`, so charts carry no title of their own — the
slide layout supplies a branded one. Pass `--titles 1` to `render.mjs` for
self-contained images (e.g. for a report rather than a deck).

## Notes

- **Charts are purpose-built, not reused from `epwCharts.js`.** That module
  draws an "all data" ghost layer under a crossfilter-filtered overlay, with
  brush handles and "% selected" labels that mean nothing in a static deck, and
  it hard-binds to ~40 DOM ids and a global `unitSystem`. The aggregation math
  in `epwDashboard.js` is deliberately identical, so the deck and the
  interactive viewer never disagree.
- **Chart colours come from the PowerPoint template's own theme** (accent1
  `#ff6600`, accent3 `#00a3b4`, dk1 `#1a1f16`, lt2 `#f4f5f0`), so the exported
  PNGs sit in the deck without a palette clash. Charts label in Open Sans, the
  template's body font; PowerPoint renders slide titles in DM Sans.
- **UTCI colours differ from the viewer on purpose.** The viewer's rainbow has
  adjacent categories that are indistinguishable (`#2e4dc2`/`#7b2abf` is ΔE 1.6
  under deuteranopia; `#00c880`/`#4dcfb0` is ΔE 7.3 for *normal* vision). The
  deck uses an ordered diverging ramp anchored on the brand teal and orange,
  strictly monotonic in lightness out from the comfort zone. Pass
  `{ utciColors: EpwOTC.utciColors }` to `drawUTCIChart` to fall back.
- **`data/usGeo.js` is generated**, by `tools/topo2geo.py` from
  [us-atlas](https://github.com/topojson/us-atlas) (Natural Earth 1:10m, public
  domain). Regenerate only if the geometry needs changing.
- **The ASHRAE climate zone comes from the sibling `.stat` file**, which
  `fetch_epw.py` saves next to each `.epw`. Recomputing it from the EPW is not
  equivalent: the A/B moisture letter needs precipitation the EPW reports too
  coarsely — Denver clears the "moist" threshold by 5 mm and so computes as 5A,
  where the published designation is 5B. The `.stat` Köppen class is likewise
  more trustworthy than the EPW-derived one (`BSk` vs `Dfa` for Denver). When no
  `.stat` is present the dashboard falls back to a thermal-only zone number from
  HDD18/CDD10 and labels it `(computed)`.
- **`lib/js/epwOTC.js` is shared.** The UTCI strategy math was extracted from
  `index.html` so the viewer and the deck compute comfort hours identically.
