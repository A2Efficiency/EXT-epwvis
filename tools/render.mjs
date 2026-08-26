/*-------------------------------------------------------------------------
 * render.mjs
 * Headless render of dashboard.html -> one PNG per chart, per location.
 *
 * Serves the repo over a throwaway localhost server (the dashboard fetches
 * the .epw, which file:// forbids), drives it with Chromium, waits for
 * window.__dashboardReady, then screenshots every [data-chart] element.
 *
 *   node tools/render.mjs                        # every entry in locations.json
 *   node tools/render.mjs --only denver          # one location by slug
 *   node tools/render.mjs --units SI --scale 2
 *
 * Output: out/<slug>/<chart>.png plus out/manifest.json for build_pptx.py.
 *-----------------------------------------------------------------------*/
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const OUT  = path.join(ROOT, 'out');

// ---- args ---------------------------------------------------------------
function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}
const UNITS = arg('units', 'IP');
const SCALE = Number(arg('scale', 3));      // 3 -> ~300 DPI for a 10in placement
const ONLY  = arg('only', null);
const HBASE = arg('hbase', null);
const CBASE = arg('cbase', null);
const OCCS  = arg('occstart', null);
const OCCE  = arg('occend', null);
const TITLES = arg('titles', '0');   // in-chart titles off by default (deck use)

// ---- static server ------------------------------------------------------
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.epw':  'text/plain; charset=utf-8',
  '.stat': 'text/plain; charset=windows-1252',
  '.zip':  'application/zip',
  '.map':  'application/json; charset=utf-8'
};

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '');
      const file = path.join(ROOT, rel);
      // Never serve outside the repo.
      if (!file.startsWith(ROOT)) { res.writeHead(403).end('forbidden'); return; }
      fs.readFile(file, (err, buf) => {
        if (err) { res.writeHead(404).end('not found'); return; }
        res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' });
        res.end(buf);
      });
    });
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
  });
}

// ---- locations ----------------------------------------------------------
function loadLocations() {
  const p = path.join(HERE, 'locations.json');
  if (!fs.existsSync(p)) {
    console.error(`missing ${p} -- create it, or run tools/fetch_epw.mjs first`);
    process.exit(1);
  }
  let list = JSON.parse(fs.readFileSync(p, 'utf8'));
  if (ONLY) list = list.filter((l) => l.slug === ONLY);
  if (!list.length) { console.error(`no locations matched --only ${ONLY}`); process.exit(1); }
  return list;
}

// ---- main ---------------------------------------------------------------
const locations = loadLocations();
const { server, port } = await serve();
const base = `http://127.0.0.1:${port}`;

const browser = await chromium.launch();
const manifest = { units: UNITS, scale: SCALE, locations: [] };

fs.mkdirSync(OUT, { recursive: true });

for (const loc of locations) {
  const epwRel = loc.epw.replace(/\\/g, '/');
  if (!fs.existsSync(path.join(ROOT, epwRel))) {
    console.error(`  SKIP ${loc.slug}: ${epwRel} not found`);
    continue;
  }

  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 1200 },
    deviceScaleFactor: SCALE
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.error(`  [page error] ${e.message}`));

  // titles=0: the PowerPoint layout supplies a branded slide title, so the
  // chart must not carry a second one.
  let url = `${base}/dashboard.html?epw=${encodeURIComponent(epwRel)}`
          + `&units=${UNITS}&export=1&titles=${TITLES}`;
  if (HBASE) url += `&hbase=${HBASE}`;
  if (CBASE) url += `&cbase=${CBASE}`;
  if (OCCS)  url += `&occstart=${OCCS}`;
  if (OCCE)  url += `&occend=${OCCE}`;

  process.stdout.write(`${loc.slug} … `);
  await page.goto(url, { waitUntil: 'networkidle' });

  // The UTCI pass is heavy; give it room before declaring failure.
  try {
    await page.waitForFunction('window.__dashboardReady === true', { timeout: 120000 });
  } catch {
    const err = await page.evaluate('window.__dashboardError || "timed out"');
    console.error(`FAILED (${err})`);
    await ctx.close();
    continue;
  }

  // Fonts must be settled or text metrics shift between runs.
  await page.evaluate(() => document.fonts.ready);

  const dir = path.join(OUT, loc.slug);
  fs.mkdirSync(dir, { recursive: true });

  // Structured metadata the page publishes for us; see dashboard.html.
  const meta = await page.evaluate(() => window.__dashboardMeta || {});
  const totals = await page.evaluate(() => window.__dashboardTotals || {});
  const station = meta.station || '';

  const names = await page.$$eval('[data-chart]', (els) =>
    els.map((e) => e.getAttribute('data-chart')));

  const charts = {};
  for (const name of names) {
    const el = await page.$(`[data-chart="${name}"]`);
    // Shoot the SVG (or table) itself, not its block-level wrapper -- the
    // wrapper spans the full viewport and would bake dead margin into the PNG.
    const target = (await el.$('svg')) || (await el.$('table')) || el;
    const box = await target.boundingBox();
    if (!box || box.width < 2 || box.height < 2) {
      console.error(`\n  WARN ${name}: empty element, skipped`);
      continue;
    }
    const file = path.join(dir, `${name}.png`);
    await target.screenshot({ path: file });
    charts[name] = path.relative(ROOT, file).replace(/\\/g, '/');
  }

  manifest.locations.push({
    slug: loc.slug,
    name: loc.name || station,
    station,
    epw: epwRel,
    meta,
    totals,
    charts
  });

  console.log(`${Object.keys(charts).length} charts -> out/${loc.slug}/`);
  await ctx.close();
}

await browser.close();
server.close();

fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log(`\nmanifest: out/manifest.json  (${manifest.locations.length} location(s))`);
