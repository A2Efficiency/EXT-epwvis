# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this repo is

A fork of [mdahlhausen/epwvis](https://github.com/mdahlhausen/epwvis), an
in-browser EnergyPlus Weather (EPW) file viewer, plus an A2E-specific pipeline
that turns weather files into a client-ready PowerPoint deck.

Two halves, kept deliberately separate:

| | Upstream viewer | A2E deck pipeline |
|---|---|---|
| Entry point | `index.html` | `dashboard.html` |
| Charts | `lib/js/epwCharts.js` | `lib/js/epwDashboard.js` |
| Purpose | interactive exploration, crossfilter | static slide-shaped figures |
| Origin | upstream | ours |

`git remote` has both `origin` (A2Efficiency) and `upstream` (mdahlhausen), and
upstream changes do get pulled.

## Rule 1: keep changes additive

**Do not modify `index.html`, `lib/js/epwCharts.js`, `lib/js/epwvis.css`, or
anything else that came from upstream** unless the task is explicitly about the
viewer. Every merge conflict costs real time. All deck work lives in files we
added:

```
dashboard.html                 the reporting dashboard page
lib/js/epwDashboard.js         the five deck charts + aggregations
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

## Running the pipeline

```bash
# one-time
cd tools && npm install && npx playwright install chromium && cd ..
pip install python-pptx

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

## Verify visually — the charts are the deliverable

A syntactically valid chart can still be unreadable. Two checks that have each
caught real bugs in this repo:

**Look at the PNGs.** Downscale and read them. Found: subtitle/legend overlap,
white labels invisible on light fills, and 25% dead whitespace baked into every
PNG (the renderer was shooting the block-level `<figure>` wrapper, not the SVG).

**Render the actual deck.** PowerPoint is installed; export slides to images via
COM and look at them:

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

## Gotchas

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
- Chromium for Playwright is a ~700 MB per-user cache in
  `%LOCALAPPDATA%\ms-playwright`, not a system install.

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
