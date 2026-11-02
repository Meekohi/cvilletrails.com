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
  if (systemId) return items.filter(item => item.system_ids.includes(systemId));
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

export function contextualSystem(systems, bounds, zoom, nearbyLayers = [], previousId = null) {
  if (!bounds) return null;
  const center = [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2];
  const area = b => (b[2] - b[0]) * (b[3] - b[1]);
  const candidates = systems.filter(system => {
    if (!system.context_mode) return false;
    const retained = system.id === previousId;
    if (zoom < (system.context_min_zoom || 13) - (retained ? .3 : 0)) return false;
    const b = system.bounds;
    const margin = retained ? .025 : 0;
    if (center[0] < b[0] - (b[2] - b[0]) * margin || center[0] > b[2] + (b[2] - b[0]) * margin
      || center[1] < b[1] - (b[3] - b[1]) * margin || center[1] > b[3] + (b[3] - b[1]) * margin) return false;
    if (system.context_mode === 'trail') return system.source_layers.some(layer => nearbyLayers.includes(layer));
    return area(bounds) <= area(b) * (retained ? 5 : 4);
  });
  return candidates.sort((a, b) => area(a.bounds) - area(b.bounds))[0] || null;
}
