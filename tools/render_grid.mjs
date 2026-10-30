/*-------------------------------------------------------------------------
 * render_grid.mjs
 * Headless render of grid.html -> one PNG per [data-chart] plus the numbers.
 *
 *   node tools/render_grid.mjs                                # tools/lllc-weather.json
 *   node tools/render_grid.mjs --config tools/other.json --out out/grid-other
 *
 * Output: <out>/<chart>.png and <out>/grid.json ({ config, stats, domains,
 * charts }) for tools/build_weather_deck.py.
 *-----------------------------------------------------------------------*/
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}
const CONFIG = arg('config', 'tools/lllc-weather.json').replace(/\\/g, '/');
const OUT = path.resolve(ROOT, arg('out', 'out/grid'));
const SCALE = Number(arg('scale', 3));

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.epw': 'text/plain; charset=utf-8', '.stat': 'text/plain; charset=windows-1252'
};

const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '');
  const file = path.join(ROOT, rel);
  if (!file.startsWith(ROOT)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404).end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' });
    res.end(buf);
  });
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1200 }, deviceScaleFactor: SCALE });
const page = await ctx.newPage();
page.on('pageerror', (e) => console.error(`  [page error] ${e.message}`));

await page.goto(`${base}/grid.html?config=${encodeURIComponent(CONFIG)}&export=1`, { waitUntil: 'networkidle' });
try {
  await page.waitForFunction('window.__gridReady === true', { timeout: 300000 });
} catch {
  console.error('FAILED: ' + await page.evaluate('window.__gridError || "timed out"'));
  process.exit(1);
}
await page.evaluate(() => document.fonts.ready);

fs.mkdirSync(OUT, { recursive: true });
const names = await page.$$eval('[data-chart]', (els) => els.map((e) => e.getAttribute('data-chart')));
const charts = {};
for (const name of names) {
  const el = await page.$(`[data-chart="${name}"]`);
  const target = (await el.$('svg')) || el;
  const file = path.join(OUT, `${name}.png`);
  await target.screenshot({ path: file });
  charts[name] = path.relative(ROOT, file).replace(/\\/g, '/');
}

const result = {
  config: JSON.parse(fs.readFileSync(path.join(ROOT, CONFIG), 'utf8')),
  configPath: CONFIG,
  stats: await page.evaluate(() => window.__gridStats),
  domains: await page.evaluate(() => window.__gridDomains),
  charts
};
fs.writeFileSync(path.join(OUT, 'grid.json'), JSON.stringify(result, null, 2));
console.log(`${Object.keys(charts).length} charts -> ${path.relative(ROOT, OUT)}/`);

await browser.close();
server.close();
