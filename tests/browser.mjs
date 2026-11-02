// Optional real-browser smoke test. Install Playwright and its Chromium browser,
// or point PLAYWRIGHT_MODULE at an existing Playwright module.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = resolve('dist');
const server = createServer(async (req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const file = resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + '/')) { res.writeHead(403).end(); return; }
  try {
    const data = await readFile(file);
    res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' })[extname(file)] || 'application/octet-stream');
    res.end(data);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(4173, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
try {
  await mkdir('test-results', { recursive: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, geolocation: { latitude: 38.031, longitude: -78.482 }, permissions: ['geolocation'] });
  const page = await context.newPage();
  // Expose the real map only inside the test response, for locating a visible trail.
  await page.route('**/assets/app.js', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, body: (await response.text()).replace('map = new mapboxgl.Map', 'map = window.__testMap = new mapboxgl.Map') });
  });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:4173/', { waitUntil: 'networkidle' });
  await page.locator('.mapboxgl-canvas').waitFor();
  await page.locator('.mapboxgl-ctrl-geolocate').waitFor();
  assert.equal(await page.locator('#panel').isVisible(), false);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: 'test-results/mobile-map.png' });
  const trailPoint = await page.evaluate(() => {
    const map = window.__testMap;
    for (const feature of map.queryRenderedFeatures().filter(f => f.layer.type === 'line' && /trail/i.test(f.layer.id))) {
      const lines = feature.geometry.type === 'MultiLineString' ? feature.geometry.coordinates : [feature.geometry.coordinates];
      for (const line of lines) for (const coordinate of line) {
        const point = map.project(coordinate);
        if (point.x > 40 && point.x < innerWidth - 70 && point.y > 100 && point.y < innerHeight - 120) return { x: point.x, y: point.y };
      }
    }
  });
  assert.ok(trailPoint, 'a real trail is rendered');
  await page.mouse.click(trailPoint.x, trailPoint.y);
  await page.locator('#panel').waitFor({ state: 'visible' });
  await page.locator('#close-panel').click();
  await page.locator('.mapboxgl-ctrl-geolocate').click();
  await page.locator('.mapboxgl-user-location-dot').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#explore').count(), 0);
  await page.evaluate(() => window.__testMap.jumpTo({ center: [-78.578, 38.026], zoom: 15 }));
  await page.waitForFunction(() => document.getElementById('map-title-text').textContent === 'Ragged Mountain Trails');
  assert.equal(await page.locator('#panel').isVisible(), false);
  await page.locator('#map-title').click();
  assert.equal(await page.locator('#panel-title').textContent(), 'Ragged Mountain');
  await page.screenshot({ path: 'test-results/mobile-details.png' });
  await page.getByRole('button', { name: 'Show on map' }).click();
  assert.equal(await page.locator('#panel').isVisible(), false);
  await page.locator('#updates').click();
  await page.getByText('No published updates here').waitFor();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#panel').isVisible(), false);
  assert.equal(await page.locator('#updates').evaluate(el => el === document.activeElement), true);
  const secret = await context.request.get('http://127.0.0.1:4173/.env.local');
  assert.equal(secret.status(), 404);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => window.__testMap.jumpTo({ center: [-78.465, 38.004], zoom: 15 }));
  await page.waitForFunction(() => document.getElementById('map-title-text').textContent === 'Saunders–Monticello Trails');
  await page.locator('#map-title').click();
  await page.screenshot({ path: 'test-results/desktop-trails.png' });
  await page.locator('#close-panel').click();
  await page.evaluate(() => window.__testMap.jumpTo({ center: [-78.482, 38.031], zoom: 11 }));
  await page.waitForFunction(() => document.getElementById('map-title-text').textContent === 'Cville Trails');
  await page.route('**/data/updates.json', route => route.fulfill({ json: { updates: [
    { id: 'test', status: 'approved', title: 'Test bridge closure', body: '<img src=x onerror=alert(1)>', kind: 'closure', system_ids: ['city'], source_url: 'https://charlottesville.gov/659/Trails', source_label: 'Test source', reviewed_at: new Date().toISOString(), starts_at: new Date(Date.now() - 100000).toISOString(), expires_at: new Date(Date.now() + 100000).toISOString() },
    { id: 'expired', status: 'approved', title: 'Expired test', body: 'Expired', kind: 'closure', system_ids: ['city'], starts_at: '2020-01-01T00:00:00Z', expires_at: '2020-02-01T00:00:00Z' }
  ] } }));
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('#updates').click();
  await page.locator('#update-scope').selectOption('all');
  await page.getByText('Test bridge closure').waitFor();
  assert.equal(await page.locator('.notice img').count(), 0);
  assert.equal(await page.getByText('Expired test').count(), 0);
  assert.deepEqual(errors, []);
  console.log('Browser checks passed: live map and trail tap, geolocation, automatic context titles, click-title details, updates, keyboard close, desktop layout, secret exclusion.');
  await context.close();
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
