const $ = (id) => document.getElementById(id);
const [report, incoming, preview, existing] = await Promise.all(['review.json', 'preview-trails.geojson', 'preview.json', 'existing-overlaps.geojson'].map(async (path) => {
  const response = await fetch(path); if (!response.ok) throw new Error(`Could not load ${path}`); return response.json();
}));
for (const collection of [incoming, existing]) {
  for (const feature of collection.features) feature.properties.review_id = feature.id;
}
const rows = new Map(report.rows.map((r) => [r.id, r]));
const features = new Map(incoming.features.map((f) => [f.id, f]));
const storageKey = `tnc-usfs-review:${report.review_hash}`;
let saved = {};
try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch { /* Fresh review if storage is unavailable. */ }
const decisions = Object.fromEntries(report.rows.map((r) => [r.id, saved.decisions?.[r.id] || (r.status === 'proposed' ? 'include' : 'hold')]));
const notes = saved.notes || {};
let selected = null;
function persist() {
  try { localStorage.setItem(storageKey, JSON.stringify({decisions, notes})); $('save-status').textContent = 'Saved in this browser'; }
  catch { $('save-status').textContent = 'Export feedback to save your decisions'; }
}
$('summary').textContent = Object.entries(report.summary).map(([k,v]) => `${v} ${k.replaceAll('-', ' ')}`).join(' · ');
$('method').textContent = report.method;
$('rejected').textContent = `${report.rejected.length} records without usable geometry were rejected and are listed in the full report.`;
for (const notice of report.notices) {
  const p = document.createElement('p'); p.className = 'notice'; const a = document.createElement('a'); a.href = notice.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = notice.title;
  p.append(a, document.createTextNode(` — ${notice.body}`)); $('notices').append(p);
}
for (const value of report.limitations) { const li = document.createElement('li'); li.textContent = value; $('limitations').append(li); }
mapboxgl.accessToken = preview.public_token;
const maps = ['before', 'after'].map((container) => new mapboxgl.Map({container, style: preview.style, center: [-79.829,37.963], zoom: 13, attributionControl: true}));
window.trailReviewMaps = maps;
let syncing = false;
for (const [i,map] of maps.entries()) {
  map.addControl(new mapboxgl.NavigationControl(), 'bottom-right');
  new ResizeObserver(() => map.resize()).observe(map.getContainer());
  map.on('move', () => { if (syncing) return; syncing = true; maps[1-i].jumpTo({center:map.getCenter(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch(),padding:map.getPadding()}); syncing = false; });
}
await Promise.all(maps.map((map) => new Promise((resolve) => map.on('load', resolve))));
const palette = ['coalesce', ['get', 'map_color'], '#8a6250'];
for (const [i,map] of maps.entries()) {
  if (i === 1) map.addSource('review', {type:'geojson', data:incoming, promoteId:'review_id'});
  if (i === 0) map.addSource('references', {type:'geojson', data:existing, promoteId:'review_id'});
  if (i === 1) {
    map.addLayer({id:'proposed-casing', type:'line', source:'review', paint:{'line-color':'#ffffff','line-width':6}});
    map.addLayer({id:'proposed', type:'line', source:'review', paint:{'line-color':'#d100ac','line-width':3}});
    map.addLayer({id:'held-records', type:'line', source:'review', paint:{'line-color':'#008d9d','line-width':3,'line-dasharray':[2,2]}});
    map.on('click', (event) => {
      const found = map.queryRenderedFeatures(event.point, {layers:['proposed','held-records']});
      if (found.length) select(found[0].id, false);
    });
  }
  map.addLayer({id:'selected', type:'line', source:i === 0 ? 'references' : 'review', filter:['==',['get','review_id'],''], paint:{'line-color':'#ff8c24','line-width':7,'line-opacity':.65}}, i === 1 ? 'proposed' : undefined);
}
function visibleRows() {
  const area = $('area').value, status = $('status').value, search = $('search').value.toLowerCase();
  return report.rows.filter((r) => (area === 'all' || r.group === area || (area === 'tnc' && r.pipeline === 'tnc-virginia') || (area === 'usfs' && r.pipeline === 'usfs-gwj')) &&
    (status === 'all' || r.status === status || (status === 'held' && !['proposed','duplicate'].includes(r.status))) && `${r.name} ${r.id}`.toLowerCase().includes(search));
}
function idFilter(ids) { return ['in', ['get','review_id'], ['literal', ids]]; }
function update(fit = false) {
  const visible = visibleRows();
  const included = visible.filter((r) => decisions[r.id] === 'include' && r.status === 'proposed').map((r) => r.id);
  for (const layer of ['proposed', 'proposed-casing']) maps[1].setFilter(layer, idFilter(included));
  maps[1].setFilter('held-records', idFilter($('held').checked ? visible.filter((r) => r.status !== 'proposed').map((r) => r.id) : []));
  maps[1].setPaintProperty('proposed', 'line-color', $('highlight').checked ? '#d100ac' : palette);
  $('count').textContent = `${visible.length} records shown · ${included.length} included`;
  $('records').replaceChildren();
  for (const row of visible) {
    const button = document.createElement('button'); button.className = `record${selected === row.id ? ' active' : ''}`; button.dataset.id = row.id;
    const name = document.createElement('span'); name.textContent = row.name;
    const detail = document.createElement('small'); detail.textContent = `${row.status.replaceAll('-',' ')} · ${(row.length_m/1609.344).toFixed(2)} mi · ${decisions[row.id]}`;
    button.append(name,detail); button.onclick = () => select(row.id); $('records').append(button);
  }
  if (fit && visible.length) fitRows(visible);
}
function fitRows(visible) {
  const bounds = new mapboxgl.LngLatBounds();
  for (const r of visible) { bounds.extend(r.bounds.slice(0,2)); bounds.extend(r.bounds.slice(2)); }
  maps[0].fitBounds(bounds, {padding:45,maxZoom:15,duration:0,retainPadding:false});
}
function select(id, fit = true) {
  selected = id; const row = rows.get(id); const feature = features.get(id);
  maps[0].setFilter('selected', idFilter(row.matches.map((m) => m.id)));
  maps[1].setFilter('selected', ['==',['get','review_id'],id]);
  if (fit) fitRows([row]);
  const container = $('detail'); container.replaceChildren();
  const h = document.createElement('h2'); h.textContent = row.name; container.append(h);
  const reason = document.createElement('p'); reason.textContent = `${row.status.replaceAll('-', ' ')}: ${row.reason}.`; container.append(reason);
  const facts = document.createElement('p'); facts.textContent = `Source: ${row.pipeline === 'tnc-virginia' ? `TNC ${feature.properties.source_map_date} GeoPDF; official map color ${row.color}` : 'USFS GIS; no blaze color supplied (neutral brown display)'}. Existing coverage within 10 / 20 / 30 m: ${['10','20','30'].map((k) => `${Math.round(row.coverage[k]*100)}%`).join(' / ')}. Orange highlights existing matches on the left and the selected source on the right.`; container.append(facts);
  const link = document.createElement('a'); link.href = row.source_url; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Open official source'; container.append(link);
  if (row.matches.length) {
    const p = document.createElement('p'); p.textContent = 'Existing matches: ' + row.matches.slice(0,6).map((m) => `${m.name} (${m.source}, ${Math.round(m.coverage_20m*100)}%)`).join('; '); container.append(p);
  }
  if (row.incoming_matches.length) {
    const p = document.createElement('p'); p.textContent = 'Incoming matches: ' + row.incoming_matches.map((id) => `${rows.get(id).name} (${rows.get(id).pipeline})`).join('; '); container.append(p);
  }
  const controls = document.createElement('label'); controls.className = 'controls'; controls.textContent = 'Decision';
  const select = document.createElement('select'); select.id = 'decision';
  for (const value of (row.status === 'proposed' ? ['include','exclude','hold'] : ['hold','exclude'])) {
    const option = document.createElement('option'); option.value = value; option.textContent = value; select.append(option);
  }
  select.value = decisions[id]; select.onchange = () => { decisions[id] = select.value; persist(); update(); }; controls.append(select); container.append(controls);
  const label = document.createElement('label'); label.textContent = row.status === 'proposed' ? 'Review note' : 'Resolution request (held trails need a follow-up before inclusion)';
  const note = document.createElement('textarea'); note.className = 'note'; note.id = 'note'; note.value = notes[id] || ''; note.oninput = () => { notes[id] = note.value; persist(); }; label.append(note); container.append(label);
  update();
}
function changeView() {
  selected = null;
  for (const map of maps) map.setFilter('selected',['==',['get','review_id'],'']);
  $('detail').replaceChildren();
  update(true);
  const first = visibleRows()[0];
  if (first) select(first.id, false);
}
for (const id of ['area','status']) $(id).onchange = changeView;
$('search').oninput = changeView;
for (const id of ['held','highlight']) $(id).onchange = () => update();
$('export').onclick = () => {
  const body = {schema_version:1,review_hash:report.review_hash,exported_at:new Date().toISOString(),decisions,notes};
  const url = URL.createObjectURL(new Blob([JSON.stringify(body,null,2)], {type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = 'tnc-usfs-feedback.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
update(true);
select(visibleRows()[0].id, false);
window.trailReviewReady = true;

for (const [id, decision] of [['include-shown','include'], ['hold-shown','hold']]) {
  $(id).onclick = () => { for (const row of visibleRows()) if (row.status === 'proposed') decisions[row.id] = decision; persist(); update(); if (selected) select(selected, false); };
}

$('fit').onclick = () => update(true);
