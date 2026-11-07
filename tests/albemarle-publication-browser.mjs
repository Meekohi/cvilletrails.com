// Verify actual public tiles after publication; no local GeoJSON overlays.
import assert from 'node:assert/strict';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
const root = process.env.ALBEMARLE_PUBLICATION_ROUND || '.trail-state/albemarle-publish-2026-11-06';
const plan = JSON.parse(await readFile(`${root}/albemarle-plan.json`, 'utf8'));
const stravaPlan = JSON.parse(await readFile(`${root}/strava-plan.json`, 'utf8'));
const beforeStyle = JSON.parse(await readFile(`${root}/inventory/style.json`, 'utf8'));
const fresh = process.argv.includes('--fresh');
const features = plan.after.features.filter(f => f.properties.reviewed_source_id);
const parks = [...new Set(features.map(f => f.properties.park_id))];
const points = f => f.geometry.type === 'LineString' ? f.geometry.coordinates : f.geometry.coordinates.flat();
const extent = list => {
  const coords = list.flatMap(points);
  return [[Math.min(...coords.map(p => p[0])), Math.min(...coords.map(p => p[1]))],
    [Math.max(...coords.map(p => p[0])), Math.max(...coords.map(p => p[1]))]];
};
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
const report = {checked_at: new Date().toISOString(), mode: fresh ? 'diagnostic-fresh-tiles' : 'ordinary-public-tiles',
  plan_hash: plan.approval_hash, parks: [], details: [], tile_headers: []};
try {
  await mkdir('test-results', {recursive: true});
  const page = await browser.newPage({viewport: {width: 1500, height: 1200}}), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', response => {
    if (!response.url().includes('/v4/') || !response.url().includes('.vector.pbf')) return;
    if (report.tile_headers.length < 12) {
      const headers = response.headers();
      report.tile_headers.push({status: response.status(), age: headers.age,
        cache_control: headers['cache-control'], x_cache: headers['x-cache']});
    }
  });
  await page.route('**/assets/app.js', async route => {
    const response = await route.fetch();
    let body = (await response.text()).replace('map = new mapboxgl.Map({', 'map = window.__testMap = new mapboxgl.Map({');
    if (fresh) body = body.replace('map = window.__testMap = new mapboxgl.Map({',
      `map = window.__testMap = new mapboxgl.Map({transformRequest:(url,type)=>({url:type==='Tile'&&url.includes('/v4/')?url+(url.includes('?')?'&':'?')+'fresh=albemarle-${Date.now()}':url}),`);
    await route.fulfill({response, body});
  });
  await page.goto(process.env.TEST_SITE_URL || 'https://cvilletrails.com/', {waitUntil: 'networkidle'});
  const ready = () => page.waitForFunction(() => window.__testMap?.loaded() && !window.__testMap.isMoving(), null, {timeout: 60000});
  await ready();
  const actualColor = await page.evaluate(() => window.__testMap.getPaintProperty('albemarle-trail', 'line-color'));
  report.palette_unchanged = JSON.stringify(actualColor) === JSON.stringify(beforeStyle.layers.find(l => l.id === 'albemarle-trail').paint['line-color']);
  for (const park of parks) {
    const group = features.filter(f => f.properties.park_id === park);
    await page.evaluate(bounds => window.__testMap.fitBounds(bounds, {padding: 100, maxZoom: 12, duration: 0}), extent(group));
    await ready();
    const data = await page.evaluate(park => {
      const map = window.__testMap;
      const rendered = map.queryRenderedFeatures({layers: ['albemarle-trail']}).filter(f => f.properties.park_id === park);
      return {zoom: map.getZoom(), records: Object.fromEntries(rendered.map(f => [f.properties.reviewed_source_id, f.properties]))};
    }, park);
    const missing = group.filter(f => !data.records[f.properties.reviewed_source_id]).map(f => f.properties.reviewed_source_id);
    const mismatched = group.filter(f => {
      const p = data.records[f.properties.reviewed_source_id];
      return p && (p.TrailName !== f.properties.TrailName || p.Property_Info !== f.properties.Property_Info);
    }).map(f => f.properties.reviewed_source_id);
    report.parks.push({park, zoom: data.zoom, expected: group.length, missing, mismatched});
    if (['walnut-creek', 'ivy-creek-natural-area', 'biscuit-run'].includes(park)) {
      await page.screenshot({path: `test-results/albemarle-published-${park}-${fresh ? 'fresh' : 'ordinary'}.png`});
    }
  }
  // Representative markers at low, middle and maximum native tile zoom.
  const markers = ['ivy-creek-natural-area', 'walnut-creek', 'preddy-creek'].map(park => features.find(f => f.properties.park_id === park));
  markers.push(features.find(f => f.properties.source_Property_Info === 'Closed'));
  for (const f of markers) {
    const coords = points(f), center = coords[Math.floor(coords.length / 2)];
    for (const zoom of [10, 14, 16]) {
      await page.evaluate(view => window.__testMap.jumpTo(view), {center, zoom});
      await ready();
      const properties = await page.evaluate(id => window.__testMap.queryRenderedFeatures({layers: ['albemarle-trail']})
        .find(f => f.properties.reviewed_source_id === id)?.properties, f.properties.reviewed_source_id);
      report.details.push({park: f.properties.park_id, source_id: f.properties.reviewed_source_id, zoom,
        present: !!properties, color_key_correct: properties?.TrailName === f.properties.TrailName,
        access_correct: properties?.Property_Info === f.properties.Property_Info});
    }
  }
  const observed = new Map();
  const stravaSource = beforeStyle.layers.find(l => l.id === 'strava-trail').source;
  report.cleanup_views = [];
  for (const f of stravaPlan.before.features.filter(f => stravaPlan.changes.deleted.includes(f.id))) {
    const coords = points(f), center = coords[Math.floor(coords.length / 2)];
    for (const zoom of [14, 16]) {
      await page.evaluate(view => window.__testMap.jumpTo(view), {center, zoom});
      await ready();
      const loaded = await page.evaluate(source => window.__testMap.querySourceFeatures(source, {sourceLayer: 'Strava_Sidetrails'})
        .map(f => ({type: 'Feature', geometry: f.geometry, properties: {}})), stravaSource);
      for (const feature of loaded) observed.set(JSON.stringify(feature.geometry), feature);
      report.cleanup_views.push({old_feature_id: f.id, zoom, loaded_fragments: loaded.length});
    }
  }
  // Quantized tile geometry is checked against the complete Strava candidate by
  // the Python geometry validator; old GPS records had no stable tile properties.
  await writeFile(`test-results/albemarle-strava-tiles-${fresh ? 'fresh' : 'ordinary'}.geojson`,
    JSON.stringify({type: 'FeatureCollection', features: [...observed.values()].map((f, i) => ({...f, id: i}))}) + '\n');
  await page.evaluate(() => window.__testMap.jumpTo({center: [-78.565, 38.033], zoom: 12}));
  await ready();
  report.ragged_visible = await page.evaluate(() => window.__testMap.queryRenderedFeatures({layers: ['albemarle-trail']})
    .filter(f => (f.properties.LocationNa || '').includes('Ragged Mountain')).length > 0);
  report.page_errors = errors;
  report.passed = report.palette_unchanged && report.ragged_visible && errors.length === 0
    && report.parks.every(p => p.missing.length === 0 && p.mismatched.length === 0)
    && report.details.every(d => d.present && d.color_key_correct && d.access_correct);
  await writeFile(`test-results/albemarle-publication-${fresh ? 'fresh' : 'ordinary'}.json`, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({mode: report.mode, passed: report.passed, parks: report.parks,
    details_passed: report.details.filter(d => d.present && d.color_key_correct && d.access_correct).length,
    ragged_visible: report.ragged_visible, palette_unchanged: report.palette_unchanged}));
  assert.ok(report.passed, 'Inspect ordinary/fresh tile evidence; publication and cache propagation differ.');
} finally { await browser.close(); }
