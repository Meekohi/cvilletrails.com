import assert from 'node:assert/strict';
import {mkdir, readFile} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
try {
  await mkdir('test-results', {recursive: true});
  const page = await browser.newPage({viewport: {width: 1600, height: 1050}}), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(process.env.ALBEMARLE_FOLLOWUP_URL || 'http://127.0.0.1:8010/followup/');
  const ready = () => page.waitForFunction(() => window.__followupReady && Object.values(window.__followupMaps).every(m => m.loaded()));
  await ready();
  const report = await page.evaluate(() => window.__followupReport);
  assert.equal(report.geometry_accepted_count, 330);
  assert.equal(report.cases.length, 27);
  assert.equal(report.publication_authorized, false);
  assert.equal(await page.locator('#title').textContent(), 'Blue Wheel');
  await page.screenshot({path: 'test-results/albemarle-colors-raw.png'});
  await page.locator('#suggestions').check();
  assert.deepEqual(await page.evaluate(() => window.__followupMaps.right.getPaintProperty('trails', 'line-color')), ['get', 'compare_suggested_color']);
  await ready();
  await page.screenshot({path: 'test-results/albemarle-colors-alias.png'});
  await page.locator('#decision').selectOption('suggested-alias');
  await page.locator('#notes').fill('Keep the established blue.');
  for (const side of ['left', 'right']) {
    const cameras = await page.evaluate(side => {
      const maps = window.__followupMaps;
      maps[side].jumpTo({center: [-78.58, 37.93], zoom: side === 'left' ? 14 : 15});
      return Object.values(maps).map(m => [m.getCenter().lng, m.getCenter().lat, m.getZoom()]);
    }, side);
    assert.deepEqual(cameras[0], cameras[1]);
  }
  await page.locator('#park').selectOption('ivy-creek-natural-area');
  const blue = report.cases.find(c => c.park_id === 'ivy-creek-natural-area' && c.name === 'Blue');
  await page.locator('#case').selectOption(blue.id);
  assert.match(await page.locator('#explanation').textContent(), /revised Red\/Blue/);
  assert.match(await page.locator('#recommendation').textContent(), /2024/);
  assert.ok(await page.locator('#decision option[value="suggested-alias"]').isDisabled());
  await page.locator('#maps summary').click();
  await page.waitForFunction(() => [...document.querySelectorAll('#maps img')].every(i => i.complete && i.naturalWidth > 0));
  await ready();
  await page.screenshot({path: 'test-results/albemarle-ivy-side-by-side.png'});
  await page.locator('#park').selectOption('biscuit-run');
  await page.locator('#south-extent').click();
  await ready();
  assert.equal(report.south.count, 46);
  assert.deepEqual(report.south.access_counts, {Closed: 46});
  assert.ok(report.south.current_rough_features > 0);
  const visible = await page.evaluate(() => {
    const {left, right} = window.__followupMaps;
    return {leftClosed: left.queryRenderedFeatures({layers: ['closed']}).length,
      rightClosed: new Set(right.queryRenderedFeatures({layers: ['closed']}).map(f => f.id)).size,
      leftCurrent: left.queryRenderedFeatures({layers: ['trails']}).length};
  });
  assert.equal(visible.leftClosed, 0);
  assert.equal(visible.rightClosed, 46);
  assert.ok(visible.leftCurrent > 0);
  await page.screenshot({path: 'test-results/albemarle-biscuit-south-comparison.png'});
  await page.locator('#south').uncheck();
  assert.equal(await page.evaluate(() => window.__followupMaps.right.getLayoutProperty('closed', 'visibility')), 'none');
  await page.locator('#south').check();
  await page.locator('#other-held').check();
  assert.equal(await page.evaluate(() => window.__followupMaps.right.getLayoutProperty('held', 'visibility')), 'visible');
  await page.locator('#other-held').uncheck();
  await page.locator('#decision').selectOption('closed-geometry');
  const pending = page.waitForEvent('download');
  await page.locator('#export').click();
  const exported = JSON.parse(await readFile(await (await pending).path(), 'utf8'));
  assert.equal(exported.review_hash, report.review_hash);
  assert.equal(exported.parent_review_hash, report.parent_review_hash);
  assert.equal(exported.geometry_feedback_hash, report.feedback_hash);
  assert.equal(exported.publication_authorized, false);
  assert.equal(exported.questions['biscuit-south'].decision, 'closed-geometry');
  assert.equal(Object.values(exported.questions).filter(v => v.decision === 'suggested-alias').length, 1);
  await page.reload(); await ready();
  assert.equal(await page.locator('#notes').inputValue(), 'Keep the established blue.');
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('#park').selectOption('biscuit-run');
  await page.locator('#south-extent').click(); await ready();
  assert.equal(await page.locator('#decision').inputValue(), 'closed-geometry');
  const panes = await page.locator('.pane').evaluateAll(nodes => nodes.map(n => ({height: n.clientHeight, width: n.clientWidth})));
  assert.ok(panes.every(p => p.height > 200 && p.height < 400 && p.width <= 390));
  await page.screenshot({path: 'test-results/albemarle-followup-mobile.png'});
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({passed: true, colors: report.cases.length, accepted: report.geometry_accepted_count,
    southernClosed: visible.rightClosed, checks: 'independent colors, camera sync, map evidence, Closed overlay, feedback export and persistence, mobile'}));
} finally { await browser.close(); }
