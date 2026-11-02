const $ = id => document.getElementById(id);
const labels = { geometry: 'Geometry changes', added: 'Additions', retained: 'Retained unmatched trails', conflict: 'Name / curation conflicts', attributes: 'Existing attribute changes', metadata: 'New metadata only', deleted: 'Deletions' };
let data, map, selected, rows = [], decisions = {}, storageKey;
const old = new Map(), proposed = new Map();
function el(tag, text) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; }
function visible() { const search = $('search').value.toLowerCase(); return rows.filter(row => ($('filter').value === 'all' || row.kinds.includes($('filter').value)) && `${row.name} ${row.id}`.toLowerCase().includes(search)); }
function save() {
  try { localStorage.setItem(storageKey, JSON.stringify(decisions)); }
  catch { $('status').textContent = 'Browser storage is unavailable. Export decisions before closing this page.'; }
  renderList();
}
function renderList() {
  $('list').replaceChildren(...visible().map(row => {
    const button = el('button'); button.setAttribute('aria-current', String(row.id === selected));
    button.append(el('strong', row.name), el('span', `${row.kinds.map(k => labels[k]).join(' · ')}${decisions[row.id]?.decision ? ' · ' + decisions[row.id].decision : ''}`));
    button.onclick = () => select(row.id); return button;
  }));
  const count = Object.values(decisions).filter(d => d.decision).length;
  $('progress').textContent = `${visible().length} shown · ${count} of ${rows.length} decisions recorded`;
}
function geometryBounds(features) {
  const points = [];
  function walk(coords) { if (typeof coords[0] === 'number') points.push(coords); else coords.forEach(walk); }
  features.filter(Boolean).forEach(f => walk(f.geometry.coordinates));
  if (!points.length) return null;
  return points.reduce((b, p) => [[Math.min(b[0][0], p[0]), Math.min(b[0][1], p[1])], [Math.max(b[1][0], p[0]), Math.max(b[1][1], p[1])]], [[Infinity, Infinity], [-Infinity, -Infinity]]);
}
function fit(features) {
  const bounds = geometryBounds(features);
  if (bounds && map) map.fitBounds(bounds, { padding: { top: 75, bottom: 70, left: 35, right: 40 }, maxZoom: 17, duration: 0 });
}
function paintSelection() {
  if (!map?.getLayer('selected-before')) return;
  for (const side of ['before', 'after']) map.setFilter(`selected-${side}`, ['==', ['get', 'review_id'], selected || '']);
}
function select(id) {
  const row = rows.find(r => r.id === id);
  if (!row) return;
  selected = id;
  $('name').textContent = row.name;
  $('feature-id').textContent = id;
  $('kinds').textContent = row.kinds.map(k => labels[k]).join(' · ');
  const explanations = [];
  if (row.kinds.includes('geometry')) explanations.push('Compare the orange current line with the blue proposal. Check junctions, access, alignment, and whether the same upstream ID still identifies this trail.');
  if (row.kinds.includes('added')) explanations.push('This segment is marked Existing in the City GIS data but absent from this City dataset. Check for duplicates in other networks and confirm public access.');
  if (row.kinds.includes('retained')) explanations.push('This curated trail has no matching Existing upstream record. The proposal keeps it. A missing source record is not treated as proof that a trail should be removed.');
  if (row.kinds.includes('metadata')) explanations.push('Geometry and existing property values are preserved. Only new fields are proposed; inspect the property table before accepting.');
  if (row.kinds.includes('attributes')) explanations.push(`Existing properties changed: ${row.changed_properties.join(', ')}. These can affect access or ownership interpretation.`);
  if (row.kinds.includes('deleted')) explanations.push('The proposal removes this feature. Accepting this item includes that deletion in a later candidate.');
  row.conflicts.forEach(c => explanations.push(`Preserved ${c.property}: ${JSON.stringify(c.curated)}. Upstream suggests ${JSON.stringify(c.upstream)}. Acceptance keeps the curated value; note a correction for discussion if needed.`));
  $('explanation').replaceChildren(...explanations.map(text => el('p', text)));
  const a = old.get(id)?.properties || {}, b = proposed.get(id)?.properties || {};
  const table = el('table');
  const head = el('tr'); ['Property', 'Before', 'Proposed'].forEach(v => head.append(el('th', v))); table.append(head);
  Object.keys({ ...a, ...b }).sort().forEach(key => {
    const row = el('tr'); if (JSON.stringify(a[key]) !== JSON.stringify(b[key])) row.className = 'changed';
    [key, key in a ? JSON.stringify(a[key]) : '—', key in b ? JSON.stringify(b[key]) : '—'].forEach(v => row.append(el('td', v))); table.append(row);
  });
  $('properties').replaceChildren(table);
  $('note').value = decisions[id]?.note || '';
  document.querySelectorAll('[data-decision]').forEach(button => button.setAttribute('aria-pressed', String(decisions[id]?.decision === button.dataset.decision)));
  renderList(); paintSelection(); fit([old.get(id), proposed.get(id)]);
}
function next(offset) {
  const list = visible(); if (!list.length) return;
  const index = list.findIndex(row => row.id === selected);
  select(list[(index + offset + list.length) % list.length].id);
}
function updateView() {
  if (!map?.getLayer('before')) return;
  for (const side of ['before', 'after']) {
    const show = $('view').value === 'overlay' || $('view').value === side;
    for (const id of [side, `selected-${side}`]) map.setLayoutProperty(id, 'visibility', show ? 'visible' : 'none');
  }
}
async function init() {
  const response = await fetch('review.json'); if (!response.ok) throw Error('Could not load the saved review');
  data = await response.json(); rows = data.rows;
  data.plan.before.features.forEach(f => old.set(String(f.id), f));
  data.plan.after.features.forEach(f => proposed.set(String(f.id), f));
  storageKey = `cville-trails-review:${data.plan.approval_hash}`;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    for (const row of rows) if (saved[row.id] && ['accept', 'defer', 'discuss', undefined].includes(saved[row.id].decision)) decisions[row.id] = saved[row.id];
  } catch { $('status').textContent = 'Previous browser notes could not be loaded. You can still review and export.'; }
  $('summary').textContent = `${data.plan.target.id} · ${data.plan.changes.added.length} additions · ${data.plan.changes.geometry_changed.length} geometry edits · Saved ${new Date(data.plan.created_at).toLocaleDateString()}`;
  const filter = $('filter');
  for (const kind of [...Object.keys(labels), 'all']) {
    const count = rows.filter(r => kind === 'all' || r.kinds.includes(kind)).length;
    if (!count) continue;
    const option = el('option', `${labels[kind] || 'All review items'} (${count})`); option.value = kind; filter.append(option);
  }
  filter.onchange = () => { renderList(); const first = visible()[0]; if (first) select(first.id); };
  $('search').oninput = renderList;
  $('prev').onclick = () => next(-1); $('next').onclick = () => next(1);
  $('view').onchange = updateView;
  $('zoom').onclick = () => fit([old.get(selected), proposed.get(selected)]);
  $('overview').onclick = () => fit([...old.values(), ...proposed.values()]);
  $('note').oninput = () => { if (!selected) return; decisions[selected] = { ...decisions[selected], note: $('note').value }; save(); };
  document.querySelectorAll('[data-decision]').forEach(button => { button.onclick = () => {
    if (!selected) return;
    decisions[selected] = { ...decisions[selected], decision: button.dataset.decision, note: $('note').value }; save(); select(selected);
  }; });
  $('export').disabled = false;
  $('export').onclick = () => {
    const content = { schema_version: 1, plan_hash: data.plan.approval_hash, exported_at: new Date().toISOString(), decisions: Object.fromEntries(Object.entries(decisions).filter(([, v]) => v.decision || v.note).map(([id, value]) => [id, { ...value, decision: value.decision || 'unreviewed' }])) };
    const blob = new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const link = el('a'); link.href = url; link.download = `${data.plan.target.id}-review-decisions.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  if (visible()[0]) select(visible()[0].id);
  if (!window.mapboxgl || !mapboxgl.supported()) throw Error('Map unavailable. The list and review decisions still work.');
  mapboxgl.accessToken = data.public_token;
  map = new mapboxgl.Map({ container: 'map', style: data.style, center: [-78.48, 38.03], zoom: 12 });
  map.addControl(new mapboxgl.NavigationControl());
  map.on('error', () => { $('status').textContent = 'Some background map data could not load. The proposal is stored locally.'; });
  map.on('load', () => {
    // Hide this dataset in the background: before/after toggles must be unambiguous.
    for (const layer of map.getStyle().layers) if (layer['source-layer'] === data.plan.target.source_layer) map.setLayoutProperty(layer.id, 'visibility', 'none');
    for (const [side, collection] of [['before', data.plan.before], ['after', data.plan.after]]) {
      map.addSource(side, { type: 'geojson', data: { type: 'FeatureCollection', features: collection.features.map(f => ({ ...f, properties: { review_id: String(f.id) } })) } });
      map.addLayer({ id: side, type: 'line', source: side, paint: { 'line-color': side === 'before' ? '#c55b24' : '#126dcc', 'line-width': side === 'before' ? 6 : 3, 'line-opacity': .65 } });
    }
    for (const side of ['before', 'after']) map.addLayer({ id: `selected-${side}`, type: 'line', source: side, filter: ['==', ['get', 'review_id'], ''], paint: { 'line-color': side === 'before' ? '#e15d18' : '#0057c2', 'line-width': side === 'before' ? 10 : 5 } });
    map.on('click', event => {
      const features = map.queryRenderedFeatures([[event.point.x - 7, event.point.y - 7], [event.point.x + 7, event.point.y + 7]], { layers: ['selected-before', 'selected-after', 'before', 'after'] });
      const hit = features.find(f => rows.some(row => row.id === f.properties.review_id));
      if (hit) { $('filter').value = 'all'; $('search').value = ''; select(hit.properties.review_id); }
    });
    updateView(); paintSelection(); fit([old.get(selected), proposed.get(selected)]);
  });
}
init().catch(error => { $('status').textContent = error.message; });
