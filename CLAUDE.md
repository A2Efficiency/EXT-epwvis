# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this repo is

A fork of [mdahlhausen/epwvis](https://github.com/mdahlhausen/epwvis), an
in-browser EnergyPlus Weather (EPW) file viewer, plus an A2E-specific pipeline
that turns weather files into a client-ready PowerPoint deck.

Two halves, kept deliberately separate:

| | Upstream viewer | A2E deck pipeline |
|---|---|---|
| Entry point | `index.html` | `dashboard.html`, `monthly.html` |
| Charts | `lib/js/epwCharts.js` | `lib/js/epwDashboard.js` |
| Purpose | interactive exploration, crossfilter | static slide-shaped figures |
| Origin | upstream | ours |

`monthly.html` is a browser-only sibling of `dashboard.html`: same chart
module, but with a weekday/weekend filter and the representative-day picker.
Nothing in the deck pipeline reads it.

`git remote` has both `origin` (A2Efficiency) and `upstream` (mdahlhausen), and
upstream changes do get pulled.

## Rule 1: keep changes additive

**Do not modify `index.html`, `lib/js/epwCharts.js`, `lib/js/epwvis.css`, or
anything else that came from upstream** unless the task is explicitly about the
viewer. Every merge conflict costs real time. All deck work lives in files we
added:

```
dashboard.html                 the reporting dashboard page
monthly.html                   day-type filtering + representative days
lib/js/epwDashboard.js         the deck charts + aggregations
lib/js/epwLocatorMap.js        US locator map (d3.geo.albersUsa)
lib/js/epwOTC.js               UTCI strategy math, shared
lib/css/epwDashboard.css       dashboard layout
data/usGeo.js                  generated US geometry
tools/                         the whole CLI pipeline
```

Known exception, already accepted: `lib/js/epwOTC.js` was extracted from
`index.html`, but `index.html` still holds its own inline copy. The two were
verified byte-identical. Wiring the viewer to the module is safe but is the one
edit that would conflict on a merge, so it was left alone.

## Rule 2: do not reuse `epwCharts.js` for the deck

It looks reusable. It is not. Those functions bail without ~40 specific DOM ids,
build a 30-dimension crossfilter, and read a global `unitSystem`. They also draw
an "all data" ghost under a filtered overlay with brush handles and "% selected"
labels, at fixed sizes like 995x314.

`epwDashboard.js` reimplements only what the deck needs. **Its aggregation math
is deliberately identical to `epwCharts.js`** (`calcDD`, `accumBins`,
`computeDailyStats`, `computeHourlyProfileByMonth`) so the deck and the viewer
can never disagree. If you touch that math, keep both sides in step.

## Setup — run this first in a fresh environment

Nothing here is vendored. In a new checkout, sandbox, or cloud session, install
these before running anything:

```bash
# 1. Node deps + the headless browser that draws the charts
cd tools
npm install
npx playwright install --with-deps chromium     # drop --with-deps on Windows/macOS
cd ..

# 2. Python deps
pip install python-pptx
```

That is the whole list. Everything else is stdlib or already vendored in `lib/`.

Requirements and caveats:

- **Node 18+** and **Python 3.9+**.
- `npx playwright install` downloads a private Chromium (~700 MB on Windows,
  less on Linux) into a per-user cache. On Linux, `--with-deps` also installs the
  system libraries Chromium needs, and may need `sudo`. If a proxy blocks the
  download, set `PLAYWRIGHT_DOWNLOAD_HOST`.
- **Network access to `climate.onebuilding.org`** is required to fetch weather
  files. That host serves a self-signed certificate, so `fetch_epw.py`
  deliberately disables TLS verification (as upstream's own
  `build_station_index.py` does). If the host is unreachable, drop `.epw` files
  into `weather_files/` by hand and write `tools/locations.json` yourself, then
  run with `--skip-fetch`.
- **No display is needed.** Chromium runs headless.
- **Fonts affect the PNGs.** Charts are drawn in Open Sans (the template's body
  font) with a Helvetica/Arial fallback. A bare Linux container has none of
  these, so Chromium substitutes something with different metrics and labels can
  shift or collide. Install them first — on Debian/Ubuntu:
  `sudo apt-get install -y fonts-open-sans fonts-liberation` — or accept that the
  PNGs will not match what this machine produced, and re-check them visually.
- **PowerPoint is not required to build the deck** — `python-pptx` writes the
  file directly. It is only used for the optional visual check below, and that
  path is Windows-only.

Verify the install with a single location:

```bash
python tools/make_deck.py "Denver-Centennial AP"
```

## Running the pipeline

```bash
python tools/make_deck.py --search denver          # find exact station names
python tools/make_deck.py "Denver-Centennial AP" "Chicago-OHare" --client "Acme"
```

`make_deck.py` chains three independently runnable steps:

```
tools/fetch_epw.py    station names  -> weather_files/*.epw + *.stat + locations.json
tools/render.mjs      locations.json -> out/<slug>/*.png + out/manifest.json
tools/build_pptx.py   manifest       -> out/climate-deck.pptx
```

Iterate on chart design in the browser, not through the deck:

```bash
python -m http.server 8000
# http://localhost:8000/dashboard.html?epw=weather_files/denver-centennial-ap.epw
```

Query params: `epw`, `units` (IP|SI), `hbase`, `cbase`, `occstart`, `occend`,
`titles` (0 suppresses in-chart titles), `export=1` (strips page chrome).

`monthly.html` takes the same `epw`, `units`, `titles` and `export`, plus
`days` (`all|weekday|weekend`), `repvar` (`dpt|dbt`), `repbasis`
(`mean|max|min`) and `repkind` (`low|median|peak`):

```bash
# http://localhost:8000/monthly.html?epw=weather_files/chicago-ohare-intl-ap.epw&days=weekend
```

## Verify visually — the charts are the deliverable

A syntactically valid chart can still be unreadable. Two checks that have each
caught real bugs in this repo:

**Look at the PNGs.** Downscale and read them. Found: subtitle/legend overlap,
white labels invisible on light fills, and 25% dead whitespace baked into every
PNG (the renderer was shooting the block-level `<figure>` wrapper, not the SVG).

**Render the actual deck.** *Windows with PowerPoint installed only* — there is
no equivalent in a Linux sandbox, so skip this step there (or use
`soffice --headless --convert-to pdf` if LibreOffice happens to be available).
Export slides to images via COM and look at them:

```powershell
$ppt = New-Object -ComObject PowerPoint.Application
$pres = $ppt.Presentations.Open("C:\GitHub\EXT-epwvis\out\climate-deck.pptx", $true, $false, $false)
$pres.Export("<outdir>", "PNG", 1900, 1069)
$pres.Close(); $ppt.Quit()
```

Found: Köppen name and description concatenated (a `<br>` vanishing into
`textContent`), a title running under the occupancy note, and a "fix" for that
which made the title wrap and overflow off-slide.

## Decisions that look wrong but are not

**ASHRAE climate zone and Köppen class come from the sibling `.stat` file, never
computed.** `fetch_epw.py` saves `<slug>.stat` next to each `.epw`;
`dashboard.html` fetches and parses it. Recomputing is not equivalent: the A/B
moisture letter needs precipitation the EPW reports too coarsely — Denver clears
the "moist" threshold by 5 mm and computes as 5A where the published designation
is 5B. The EPW-derived Köppen is wrong there too (`Dfa` vs the correct `BSk`).
There is a thermal-only fallback for files with no `.stat`; it is labelled
`(computed)` on purpose. `.stat` files are cp1252, not UTF-8.

**Chart colours come from the PowerPoint template's theme**, read out of
`2026_Presentation A2E General Blank.pptx`: accent1 `#ff6600`, accent3
`#00a3b4`, dk1 `#1a1f16`, lt2 `#f4f5f0`, body font Open Sans. Charts label in
Open Sans; PowerPoint renders slide titles in DM Sans (not installed locally,
which is fine).

**The UTCI ramp deliberately differs from the viewer's.** The viewer's rainbow
has adjacent categories nobody can separate — `#2e4dc2`/`#7b2abf` is ΔE 1.6
under deuteranopia and `#00c880`/`#4dcfb0` is ΔE 7.3 for *normal* vision. The
deck uses an ordered diverging ramp anchored on brand teal and orange, strictly
monotonic in lightness out from the comfort zone. Pass
`{ utciColors: EpwOTC.utciColors }` to fall back.

**Validate any new palette; do not eyeball it.** Use the `dataviz` skill's
`scripts/validate_palette.js`. For an ordered ramp the categorical lightness-band
and chroma checks do not apply — the criterion there is monotonic lightness plus
adjacent separation.

**Occupied hours use a midpoint rule.** EPW hour `h` spans `(h-1):01` to `h:00`,
midpoint `h-0.5`; an hour is occupied when that midpoint falls in
`[start, end)`. 7→19 selects EPW hours 8..19 — twelve hours, 4,380 of 8,760.

**`data/usGeo.js` is generated** by `tools/topo2geo.py` from us-atlas (Natural
Earth 1:10m, public domain). Territories are stripped because
`d3.geo.albersUsa` cannot project them. Regenerate only to change geometry.

**Weekday/weekend comes from the EPW's `DATA PERIODS` header, not the year
column.** Field 4 of that line names the day of week for day 1 (`Sunday` in
every OneBuilding file we handle) and `startDayOfWeek()` counts forward from
it. The year column cannot be used: a TMYx year splices months from different
real years — `chicago-ohare-intl-ap.epw` carries 2011 through 2022 — so no
single calendar applies. EnergyPlus takes the weekday from this same header
when it simulates the file, so a weekend split built on it matches the
schedules a model would actually run.

**Dew point is orange, dry bulb is teal, and that pairing was validated not
guessed.** Dry bulb was already teal in the deck's two temperature charts, so
dew point had to take the other brand pole. The two-series day charts use
`PALETTE.dbtPair`/`dewPair` (`#0090a2`/`#e55a00`), which pass all six checks in
the `dataviz` skill's `scripts/validate_palette.js`. Two things that look
reasonable and are not: `#007a88` (the existing `tempLine`) misses the chroma
floor as a categorical slot, and brand green `#4a8b2c` against the teal is
ΔE 4.3 under tritanopia — indistinguishable. The single-series clouds keep
`tempLine`, where the categorical checks do not apply.

**A representative day is a real date, never a composite.** Days in a month are
ranked by one statistic of one variable (`monthlyRepresentativeDays(days, key,
basis)`), and low/median/peak are read off that ranking, so the plotted profile
is the actual hour-by-hour weather of a day you can point at. Even-length
months take the lower of the two middle days, deterministically, rather than
depending on sort stability.

## Gotchas

- **Every chart SVG needs a `viewBox`.** Without one, `max-width: 100%` shrinks
  the SVG *viewport* without scaling its contents, so the chart is silently
  **cropped** rather than resized — this is what hid December in the 1180px-wide
  profile strip on a 998px-wide page. `.dash-page` is also sized (1260px) so the
  widest chart lands at native size. Export mode is unaffected: it sets
  `max-width: none` in a 1280px viewport, so the PNGs are pixel-identical.
- **Adding a figure to `dashboard.html` perturbs the PNGs below it** by a
  handful of sub-pixel antialiasing bytes (~0.002% of the image) — the element
  screenshots land on different fractional page offsets. Expect a diff in `out/`
  for charts under the insertion point; it is not a layout change.
- **Chart sizes are matched to slide slots** in `build_pptx.py`. Changing a
  chart's `width`/`height` in `dashboard.html` changes its aspect ratio and will
  letterbox it on the slide. Change both together.
- **`out/` and `weather_files/` are gitignored.** Generated decks and PNGs do
  not travel through git; a colleague regenerates them.
- **Paths passed to `build_pptx.py` may be relative or absolute** — use its
  `resolve()` helper, not bare `Path()`.
- **d3 is v3**, not v4+. No `fitExtent`, no `d3.scaleLinear`. Use `d3.scale.*`,
  `d3.svg.*`, `d3.geo.*`.
- **This Bash tool mangles quoted heredocs containing apostrophes.** For
  multi-line JS or Python edits, use the Write tool, or write a script file to
  the scratchpad and run it.
- Chromium for Playwright is a per-user cache (`%LOCALAPPDATA%\ms-playwright`
  on Windows, `~/.cache/ms-playwright` on Linux), not a system install.
- **`tools/node_modules/` is gitignored**, so a fresh clone always needs
  `npm install` before `render.mjs` will run.

## Deck structure

Title slide, then two slides per location:

1. **Location** — station facts, ASHRAE zone + Köppen, locator map, UTCI hours
   breakdown, annual temperature, daily profile strip.
2. **Degree days** — degree days by temperature bin and by month (occupied hours
   solid over pale all-hours), headline occupied HDD/CDD with the unfiltered site
   totals in bold, assumptions, occupancy note at the foot.

Layout names are constants at the top of `build_pptx.py` (`L_TITLE`, `L_BLANK`,
`L_TITLE_ONLY`) and must match the template exactly. The template also ships six
sample slides, which `drop_existing_slides()` removes.

See `tools/README.md` for the user-facing version of all this.
