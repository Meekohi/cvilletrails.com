import test from 'node:test';
import assert from 'node:assert/strict';
import { activeUpdates, visibleUpdates, featureName, safeLink, contextualSystem } from '../assets/data.js';

test('only approved, active, unexpired notices appear; malformed dates fail closed', () => {
  const now = Date.parse('2026-11-02T12:00:00Z');
  const base = { id: 'active', status: 'approved', starts_at: '2026-11-01T00:00:00Z', expires_at: '2026-11-03T00:00:00Z' };
  assert.deepEqual(activeUpdates([base, { ...base, status: 'draft' }, { ...base, starts_at: '2026-11-04T00:00:00Z' }, { ...base, expires_at: '2026-11-02T12:00:00Z' }, { ...base, expires_at: null }], now), [base]);
});
test('update relevance follows map area and explicit system selection', () => {
  const systems = [{ id: 'a', bounds: [0, 0, 2, 2] }, { id: 'b', bounds: [10, 10, 12, 12] }];
  const items = [{ id: 1, system_ids: ['a'] }, { id: 2, system_ids: ['b'] }];
  assert.deepEqual(visibleUpdates(items, systems, [1, 1, 3, 3]), [items[0]]);
  assert.deepEqual(visibleUpdates(items, systems, [1, 1, 3, 3], 'all'), items);
  assert.deepEqual(visibleUpdates(items, systems, [1, 1, 3, 3], 'map', 'b'), [items[1]]);
});
test('legacy property names work and unsafe URLs never become links', () => {
  assert.equal(featureName({ TrailName: 'Wilkins Way' }), 'Wilkins Way');
  assert.equal(featureName({ NAME: 'Meadow Creek' }), 'Meadow Creek');
  assert.equal(safeLink('javascript:alert(1)'), null);
  assert.equal(safeLink('https://www.rivannatrails.org/Map'), 'https://www.rivannatrails.org/Map');
});

test('context titles select focused parks, avoid broad regions, and reset when zoomed out', () => {
  const city = { id: 'city', bounds: [-80, 36, -77, 40] };
  const park = { id: 'park', bounds: [-78.49, 38, -78.44, 38.03], context_mode: 'area' };
  assert.equal(contextualSystem([city, park], [-78.48, 38.005, -78.45, 38.025], 15), park);
  assert.equal(contextualSystem([city, park], [-78.48, 38.005, -78.45, 38.025], 11), null);
  assert.equal(contextualSystem([city, park], [-78.6, 38.1, -78.55, 38.15], 15), null);
  assert.equal(contextualSystem([city, park], [-79, 37.5, -78, 38.5], 14), null);
});
test('a citywide ring needs a nearby rendered trail, and the smaller park wins overlaps', () => {
  const ring = { id: 'ring', bounds: [-78.6, 37.9, -78.4, 38.2], context_mode: 'trail', source_layers: ['Ring'] };
  const park = { id: 'park', bounds: [-78.5, 38, -78.45, 38.05], context_mode: 'area' };
  const view = [-78.49, 38.01, -78.46, 38.04];
  assert.equal(contextualSystem([ring], view, 15), null);
  assert.equal(contextualSystem([ring], view, 15, ['Ring']), ring);
  assert.equal(contextualSystem([ring, park], view, 15, ['Ring']), park);
});
