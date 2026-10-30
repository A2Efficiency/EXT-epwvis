/*-------------------------------------------------------------------------
 * render_zone_grid.mjs
 * Headless render of zonegrid.html -> one PNG holding the whole grid.
 *
 * Scans a directory of .epw files, reads each one's ASHRAE climate zone out of
 * its sibling .stat, writes a manifest, then drives zonegrid.html with Chromium
 * and screenshots the single grid SVG.
 *
 * The whole grid is ONE image on purpose. Fourteen separate PNGs placed by
 * PowerPoint coordinates cannot share a y scale or line up their panels; an SVG
 * can do both exactly.
 *
 *   node tools/render_zone_grid.mjs
 *   node tools/render_zone_grid.mjs --dir weather_data --months 1,7 --scale 3
 *   node tools/render_zone_grid.mjs --units SI --width 1600 --height 860
 *
 * Output: out/zonegrid/climate-zones.png + out/zonegrid/manifest.json
 *-----------------------------------------------------------------------*/
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');

// ---- args ---------------------------------------------------------------
function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}
const DIR    = arg('dir', 'weather_data');
const MONTHS = arg('months', '1,7');
const UNITS  = arg('units', 'IP');
const WIDTH  = Number(arg('width', 1600));
const HEIGHT = Number(arg('height', 760));  // aspect tuned to the slide-1 image box
const SCALE  = Number(arg('scale', 3));      // 3 -> ~280 DPI at 16in wide
// 'row' -- one scale per month, shared across every location. Locations stay
// exactly as comparable (that is the within-row reading); the two months are
// no longer on the same scale and must not be read against each other.
const SHAREY = arg('sharey', 'row');         // 'all' | 'row'  (see drawZoneMonthGrid)
const NAME   = arg('name', 'climate-zones');
const BANDW  = Number(arg('bandwidth', 340));   // per-location comfort-band chart
const BANDH  = Number(arg('bandheight', 290));
const MAPW   = Number(arg('mapwidth', 700));    // study locator map
const MAPH   = Number(arg('mapheight', 400));
const OUTDIR = path.join(ROOT, arg('outdir', path.join('out', 'zonegrid')));

// ---- climate zone, from the .stat and nowhere else ----------------------
/*
 * The same two regexes dashboard.html uses. Recomputing the zone is NOT
 * equivalent -- the A/B moisture letter needs precipitation the EPW reports too
 * coarsely, and Denver comes out 5A against a published 5B. See CLAUDE.md.
 *
 * .stat files are cp1252, not UTF-8.
 */
function readStat(statPath) {
  if (!fs.existsSync(statPath)) return {};
  const text = new TextDecoder('windows-1252').decode(fs.readFileSync(statPath));
  const out = {};
  const z = text.match(/Climate Zone\s+"([^"]+)"\s*\(ASHRAE\s+([^)]*)\)/i);
  if (z) {
    out.zone = z[1].trim();
    out.zonePublished = /^Standard\s+/i.test(z[2].trim());
  }
  const d = text.match(
    /\n\s*-?\s*([A-Za-z][A-Za-z \-]*?)\s*,\s*Probable K\S*ppen classification\s*=\s*([^,\n]+)\s*,\s*([^\n]+)/i);
  if (d) {
    out.zoneName = d[1].trim();
    out.koppen = d[2].trim();
  }
  return out;
}

/*
 * "USA_TX_Houston-Bush.Intercontinental.AP.722430_TMYx.2011-2025" ->
 * "Houston, TX". Column headings get about 200px, so the station's full name
 * will not fit and the city plus state is what identifies it on a slide.
 *
 * OneBuilding stems use "." as a word separator inside a name and "-" between
 * the place and the facility, so the order matters: cut at the first "-" to
 * drop the facility, then keep dot-separated words until a facility marker or a
 * WMO number. Splitting on "." first turns "New.York-Central.Park" into "New".
 */
const FACILITY = new Set([
  'intl', 'international', 'ap', 'airport', 'afb', 'muni', 'municipal', 'rgnl',
  'regional', 'obs', 'observatory', 'field', 'nas', 'army', 'natl', 'national',
  'monument', 'wso', 'wso-ap', 'co-op', 'agrimet'
]);

function cityLabel(stem) {
  const parts = stem.split('_');
  const state = parts.length > 1 ? parts[1] : '';
  const place = (parts.length > 2 ? parts[2] : stem).split('-')[0];

  const words = [];
  for (const tok of place.split('.')) {
    if (!tok) continue;
    if (/^\d+$/.test(tok) || FACILITY.has(tok.toLowerCase())) break;
    words.push(tok.replace(/([a-z])([A-Z])/g, '$1 $2'));
  }
  const name = (words.length ? words.join(' ') : place) || stem;
  return state ? name + ', ' + state : name;
}

/*
 * Optional <dir>/labels.json, { "<epw stem>": "Nice Name" }, so a column can be
 * relabelled without editing this file.
 */
function labelOverrides(absDir) {
  const f = path.join(absDir, 'labels.json');
  if (!fs.existsSync(f)) return {};
  try {
    return JSON.parse(fs.readFileSync(f, 'utf8'));
  } catch (e) {
    console.error(`  WARNING: ignoring unreadable ${f}: ${e.message}`);
    return {};
  }
}

/* Width and height out of the PNG's own IHDR, rather than assuming w*scale. */
function pngSize(file) {
  const b = fs.readFileSync(file);
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
}

function collect(dir) {
  const abs = path.isAbsolute(dir) ? dir : path.join(ROOT, dir);
  if (!fs.existsSync(abs)) {
    console.error(`\n  Directory not found: ${abs}\n`);
    process.exit(1);
  }
  const over = labelOverrides(abs);
  const rows = fs.readdirSync(abs)
    .filter(f => f.toLowerCase().endsWith('.epw'))
    .map(f => {
      const stem = f.replace(/\.epw$/i, '');
      const stat = readStat(path.join(abs, stem + '.stat'));
      return {
        epw:  path.posix.join(...path.relative(ROOT, path.join(abs, f)).split(path.sep)),
        stem,
        city: over[stem] || cityLabel(stem),
        zone: stat.zone || '?',
        zoneName: stat.zoneName || '',
        koppen: stat.koppen || '',
        zonePublished: !!stat.zonePublished
      };
    });

  // Warm to cold, which is how a climate-zone sweep is read. Zone numbers sort
  // numerically and the A/B/C moisture letter breaks ties; anything with no
  // .stat zone lands at the end rather than sorting as zone 0.
  rows.sort((a, b) => {
    const key = r => {
      const m = /^(\d+)([A-C]?)$/i.exec(r.zone);
      return m ? [Number(m[1]), m[2].toUpperCase()] : [99, 'Z'];
    };
    const [an, al] = key(a), [bn, bl] = key(b);
    return an - bn || al.localeCompare(bl) || a.city.localeCompare(b.city);
  });
  return rows;
}

// ---- static server ------------------------------------------------------
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.epw':  'text/plain; charset=utf-8',
  '.stat': 'text/plain; charset=windows-1252'
};

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '');
      const file = path.join(ROOT, rel);
      if (!file.startsWith(ROOT)) { res.writeHead(403).end('forbidden'); return; }
      fs.readFile(file, (err, buf) => {
        if (err) { res.writeHead(404).end('not found'); return; }
        res.writeHead(200, {
          'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream'
        });
        res.end(buf);
      });
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

// ---- main ---------------------------------------------------------------
const columns = collect(DIR);
if (!columns.length) {
  console.error(`\n  No .epw files in ${DIR}\n`);
  process.exit(1);
}

fs.mkdirSync(OUTDIR, { recursive: true });
const manifest = {
  generated: new Date().toISOString(),
  source: DIR,
  units: UNITS,
  months: MONTHS.split(',').map(Number),
  width: WIDTH,
  height: HEIGHT,
  scale: SCALE,
  shareY: SHAREY,
  columns
};
const manPath = path.join(OUTDIR, NAME + '.json');
fs.writeFileSync(manPath, JSON.stringify(manifest, null, 2));

const missing = columns.filter(c => c.zone === '?');
console.log(`\n  ${columns.length} weather files in ${DIR}`);
for (const c of columns) {
  console.log(`    ${c.zone.padEnd(4)} ${c.city.padEnd(18)} ${c.zoneName}`);
}
if (missing.length) {
  console.log(`\n  WARNING: no ASHRAE zone in the .stat for: ` +
              missing.map(c => c.stem).join(', '));
}
const dupes = [...new Set(columns.map(c => c.zone))]
  .filter(z => columns.filter(c => c.zone === z).length > 1);
if (dupes.length) {
  console.log(`  NOTE: zone ${dupes.join(', ')} appears more than once ` +
              `-- ${columns.length} files, ${new Set(columns.map(c => c.zone)).size} distinct zones.`);
}

const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const manRel = path.posix.join(...path.relative(ROOT, manPath).split(path.sep));

const browser = await chromium.launch();
// The viewport must exceed the SVG or the page scrollbar shifts the element
// screenshot; deviceScaleFactor is what actually sets the output resolution.
const page = await browser.newPage({
  viewport: { width: WIDTH + 80, height: HEIGHT + 80 },
  deviceScaleFactor: SCALE
});
page.on('pageerror', e => console.error('  page error:', e.message));

const url = `${base}/zonegrid.html?manifest=${encodeURIComponent(manRel)}` +
            `&months=${MONTHS}&units=${UNITS}&width=${WIDTH}&height=${HEIGHT}` +
            `&titles=0&export=1&sharey=${SHAREY}` +
            `&bandwidth=${BANDW}&bandheight=${BANDH}` +
            `&mapwidth=${MAPW}&mapheight=${MAPH}`;
await page.goto(url, { waitUntil: 'networkidle' });
try {
  await page.waitForFunction(() => window.__zoneGridReady === true, { timeout: 120000 });
} catch (e) {
  const err = await page.evaluate(() => window.__zoneGridError || 'timed out');
  await browser.close(); server.close();
  console.error(`\n  Render failed: ${err}\n`);
  process.exit(1);
}

const el = await page.$('#chartZoneGrid svg');
const pngPath = path.join(OUTDIR, NAME + '.png');
await el.screenshot({ path: pngPath });

const mapEl = await page.$('#chartSites svg');
if (mapEl) {
  const mapPath = path.join(OUTDIR, NAME + '-map.png');
  await mapEl.screenshot({ path: mapPath });
  manifest.map = path.posix.join(...path.relative(ROOT, mapPath).split(path.sep));
}

// One comfort-band chart per location, shot individually. Unlike the grid these
// do not need to line up with each other -- PowerPoint places them -- and they
// already share an x domain, which is what makes them comparable.
const bandDir = path.join(OUTDIR, 'bands');
fs.mkdirSync(bandDir, { recursive: true });
for (const [i, c] of columns.entries()) {
  const fig = await page.$(`#chartBand${i} svg`);
  if (!fig) { console.error(`  no band chart for ${c.stem}`); continue; }
  const slug = `${c.zone}-${c.city}`.toLowerCase().replace(/[^a-z0-9]+/g, '-')
                                    .replace(/^-|-$/g, '');
  const out = path.join(bandDir, `${slug}.png`);
  await fig.screenshot({ path: out });
  c.bandPng = path.posix.join(...path.relative(ROOT, out).split(path.sep));
}

const { width, height } = pngSize(pngPath);
manifest.png = path.posix.join(...path.relative(ROOT, pngPath).split(path.sep));
manifest.pngWidth = width;
manifest.pngHeight = height;
fs.writeFileSync(manPath, JSON.stringify(manifest, null, 2));

await browser.close();
server.close();

const nBands = columns.filter(c => c.bandPng).length;
console.log(`\n  Wrote ${manifest.png}  (${width}x${height} px, ` +
            `${(fs.statSync(pngPath).size / 1024).toFixed(0)} KB)`);
if (manifest.map) console.log(`  Wrote ${manifest.map}`);
console.log(`  Wrote ${nBands} comfort-band charts to ` +
            `${path.posix.join(...path.relative(ROOT, bandDir).split(path.sep))}/`);
console.log(`  Wrote ${path.posix.join(...path.relative(ROOT, manPath).split(path.sep))}\n`);
