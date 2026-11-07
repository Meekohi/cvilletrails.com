import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';
const system = JSON.parse(await readFile('data/systems.json', 'utf8')).find(s => s.id === 'biscuit-run');
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
try {
  await mkdir('test-results', {recursive: true});
  const page = await browser.newPage({viewport: {width: 1200, height: 900}});
  await page.emulateMedia({reducedMotion: 'reduce'});
  await page.route('**/assets/app.js', async route => {
    const response = await route.fetch();
    const body = (await response.text()).replace('map = new mapboxgl.Map({',
      'map = window.__testMap = new mapboxgl.Map({');
    await route.fulfill({response, body});
  });
  await page.goto(process.env.TEST_SITE_URL || 'http://127.0.0.1:8000/', {waitUntil: 'networkidle'});
  await page.waitForFunction(() => window.__testMap?.loaded());
  for (const viewport of [{width: 1200, height: 900}, {width: 390, height: 844}]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => window.__testMap.jumpTo({center: [-78.525, 37.972], zoom: 16}));
    await page.waitForFunction(() => document.querySelector('#map-title-text').textContent === 'Biscuit Run Park');
    await page.locator('#map-title').click();
    assert.equal(await page.locator('#panel-title').textContent(), 'Biscuit Run Park');
    assert.equal(await page.locator('.map-note').count(), 0);
    await page.evaluate(() => window.__testMap.jumpTo({center: [-78.482, 38.031], zoom: 11}));
    await page.waitForFunction(() => document.querySelector('#map-title-text').textContent === 'Cville Trails');
    await page.locator('#map-title').click();
    await page.getByRole('button', {name: 'Biscuit Run Park', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#panel-title').textContent === 'Biscuit Run Park' && !window.__testMap.isMoving());
    const fits = await page.evaluate(b => {
      const map = window.__testMap, panel = document.querySelector('#panel').getBoundingClientRect();
      return [[b[0], b[1]], [b[2], b[3]]].map(p => map.project(p)).every(p => p.x >= 0 && p.x <= innerWidth
        && p.y >= 89 && p.y <= innerHeight - 100 && (innerWidth <= 600 ? p.y < panel.top : p.x > panel.right));
    }, system.bounds);
    assert.ok(fits, 'Biscuit overview includes both the north and newly mapped south');
    await page.screenshot({path: `test-results/biscuit-context-${viewport.width}.png`});
  }
  console.log('Southern Biscuit automatic context and complete park framing passed on desktop and mobile.');
} finally { await browser.close(); }
