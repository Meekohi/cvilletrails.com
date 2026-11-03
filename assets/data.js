export function intersects(a, b) {
  return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
}

export function activeUpdates(items, now = Date.now()) {
  return items.filter(item => item.status === 'approved'
    && Number.isFinite(Date.parse(item.starts_at)) && Date.parse(item.starts_at) <= now
    && Number.isFinite(Date.parse(item.expires_at)) && Date.parse(item.expires_at) > now)
    .sort((a, b) => (a.kind === 'closure' ? 0 : 1) - (b.kind === 'closure' ? 0 : 1)
      || Date.parse(b.starts_at) - Date.parse(a.starts_at));
}

export function visibleUpdates(items, systems, bounds, scope = 'map', systemId = null) {
  if (systemId) {
    const system = systems.find(s => s.id === systemId);
    const related = new Set([systemId, ...(system?.parent_ids || []), ...systems.filter(s => s.parent_ids?.includes(systemId)).map(s => s.id)]);
    return items.filter(item => item.system_ids.some(id => related.has(id)));
  }
  if (scope === 'all' || !bounds) return items;
  const visible = new Set(systems.filter(system => intersects(system.bounds, bounds)).map(system => system.id));
  return items.filter(item => item.system_ids.some(id => visible.has(id)));
}

export function featureName(properties = {}) {
  return ['name', 'TrailName', 'NAME', 'Name', 'TRAILNAME', 'Trail_Name']
    .map(key => properties[key]).find(value => typeof value === 'string' && value.trim()) || 'Trail';
}

export function safeLink(value) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; }
  catch { return null; }
}

const boundsArea = b => (b[2] - b[0]) * (b[3] - b[1]);

function inRing(point, ring) {
  let inside = false;
  const [x, y] = point;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function containsLocation(system, point, margin = 0) {
  const b = system.bounds;
  if (!point || point[0] < b[0] - (b[2] - b[0]) * margin || point[0] > b[2] + (b[2] - b[0]) * margin
    || point[1] < b[1] - (b[3] - b[1]) * margin || point[1] > b[3] + (b[3] - b[1]) * margin) return false;
  if (!system.boundary) return true;
  const polygons = system.boundary.type === 'Polygon' ? [system.boundary.coordinates] : system.boundary.coordinates;
  return polygons.some(rings => inRing(point, rings[0]) && !rings.slice(1).some(ring => inRing(point, ring)));
}

export function systemForFeature(systems, feature, point) {
  // A shared City/County/RT layer does not identify a park. Resolve a local
  // system at the tap first, then use the feature's broader source identity.
  const local = systems.filter(s => s.context_mode && s.id !== 'rivanna'
    && s.source_layers.includes(feature.sourceLayer) && containsLocation(s, point));
  if (local.length) return local.sort((a, b) => boundsArea(a.bounds) - boundsArea(b.bounds))[0];
  const declared = systems.find(s => s.id === feature.properties?.system_id);
  if (declared && (!declared.context_mode || containsLocation(declared, point))) return declared;
  const matches = systems.filter(s => s.source_layers.includes(feature.sourceLayer));
  return matches.find(s => !s.context_mode || s.id === 'rivanna')
    || matches.find(s => containsLocation(s, point)) || (matches.length === 1 ? matches[0] : null);
}

export function contextualSystem(systems, bounds, zoom, nearbyLayers = [], previousId = null) {
  if (!bounds) return null;
  const center = [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2];
  const candidates = systems.filter(system => {
    if (!system.context_mode) return false;
    const retained = system.id === previousId;
    if (zoom < (system.context_min_zoom || 13) - (retained ? .3 : 0)) return false;
    const margin = retained ? .025 : 0;
    if (!containsLocation(system, center, margin)) return false;
    if (system.context_mode === 'trail') return system.source_layers.some(layer => nearbyLayers.includes(layer));
    return boundsArea(bounds) <= boundsArea(system.bounds) * (system.context_max_view_ratio || 4) * (retained ? 1.25 : 1);
  });
  return candidates.sort((a, b) => boundsArea(a.bounds) - boundsArea(b.bounds))[0] || null;
}
