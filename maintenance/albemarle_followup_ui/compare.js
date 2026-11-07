(async () => {
  const $ = id => document.getElementById(id);
  const [report, current, incoming, config] = await Promise.all(['review.json', 'current.geojson', 'incoming.geojson', 'preview.json'].map(async file => {
    const response = await fetch(file); if (!response.ok) throw new Error(`Could not load ${file}`); return response.json();
  }));
  window.__followupReport = report;
  $('status').textContent = `Your approval of all ${report.geometry_accepted_count} magenta geometries is recorded. This round resolves color questions and the southern coverage gap.`;
  const storageKey = `albemarle-followup:${report.review_hash}`;
  let state = {questions: {}};
  try { state = JSON.parse(localStorage.getItem(storageKey)) || state; } catch { /* No saved feedback. */ }
  let selectedCase, activeKey, syncing = false;
  mapboxgl.accessToken = config.public_token;
  const left = new mapboxgl.Map({container: 'left', style: 'mapbox://styles/mapbox/outdoors-v12', center: [-78.59, 37.925], zoom: 13});
  const right = new mapboxgl.Map({container: 'right', style: 'mapbox://styles/mapbox/outdoors-v12', center: [-78.59, 37.925], zoom: 13});
  window.__followupMaps = {left, right};
  for (const [map, other] of [[left, right], [right, left]]) {
    map.addControl(new mapboxgl.NavigationControl(), 'top-right');
    map.on('move', () => {
      if (syncing) return;
      syncing = true;
      other.jumpTo({center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch()});
      syncing = false;
    });
  }
  await Promise.all([left, right].map(map => new Promise(resolve => map.on('load', resolve))));
  function add(map, data) {
    map.addSource('trails', {type: 'geojson', data, promoteId: 'compare_id'});
    map.addLayer({id: 'fringe', type: 'line', source: 'trails', paint: {'line-color': '#453422', 'line-width': 7}});
    map.addLayer({id: 'trails', type: 'line', source: 'trails', paint: {'line-color': ['get', 'compare_color'], 'line-width': 4}});
    map.addLayer({id: 'closed', type: 'line', source: 'trails', paint: {'line-color': '#a95713', 'line-width': 4, 'line-dasharray': [2, 2]}});
    map.addLayer({id: 'held', type: 'line', source: 'trails', paint: {'line-color': '#686868', 'line-width': 2, 'line-dasharray': [2, 3]}});
    map.addLayer({id: 'names', type: 'symbol', source: 'trails', minzoom: 12, layout: {'symbol-placement': 'line', 'text-field': ['get', 'compare_name'], 'text-size': 12, 'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular']}, paint: {'text-color': '#243b35', 'text-halo-color': '#ffffff', 'text-halo-width': 2}});
  }
  for (const data of [current, incoming]) for (const f of data.features) f.properties.compare_id = f.id;
  add(left, current); add(right, incoming);
  const fit = b => left.fitBounds([[b[0], b[1]], [b[2], b[3]]], {padding: {top: 80, right: 35, bottom: 40, left: 35}, maxZoom: 17.5, duration: 0});
  function save() {
    state.questions[activeKey] = {decision: $('decision').value, notes: $('notes').value};
    try { localStorage.setItem(storageKey, JSON.stringify(state)); $('saved').textContent = 'Feedback saved in this browser. Export when finished.'; }
    catch { $('saved').textContent = 'Browser storage unavailable; export feedback before closing.'; }
  }
  $('decision').onchange = $('notes').oninput = save;
  function setDecisions(options) {
    $('decision').replaceChildren();
    for (const [value, title] of options) { const o = document.createElement('option'); o.value = value; o.textContent = title; $('decision').append(o); }
    $('decision').value = state.questions[activeKey]?.decision || '';
    $('notes').value = state.questions[activeKey]?.notes || '';
  }
  function links(ids) {
    $('source-links').replaceChildren();
    for (const id of [...new Set([...ids, 'county-gis'])]) {
      const s = report.evidence.sources[id], a = document.createElement('a'); a.href = s.file ? `evidence/${s.file}` : s.url;
      a.textContent = s.title; a.target = '_blank'; a.rel = 'noopener'; $('source-links').append(a);
    }
  }
  function swatch(title, color) {
    const p = document.createElement('p'), span = document.createElement('span'); span.className = 'swatch'; span.style.backgroundColor = color;
    p.append(span, document.createTextNode(title)); $('swatches').append(p);
  }
  function renderLayers() {
    const park = $('park').value, southMode = park === 'biscuit-run';
    const scope = ['==', ['get', 'compare_park'], park];
    const leftIds = selectedCase?.old_records.map(r => r.id) || [];
    for (const [map, side] of [[left, 'left'], [right, 'right']]) {
      const category = side === 'left' ? 'current' : 'eligible';
      const base = ['all', scope, ['==', ['get', 'compare_category'], category]];
      const selected = side === 'left' ? ['in', ['get', 'compare_id'], ['literal', leftIds]] : ['==', ['get', 'compare_id'], selectedCase?.id || ''];
      const filter = southMode || $('context').checked ? base : ['all', base, selected];
      const opacity = southMode ? 1 : ['case', selected, 1, .32];
      for (const id of ['fringe', 'trails']) { map.setFilter(id, filter); map.setPaintProperty(id, 'line-opacity', opacity); }
      map.setFilter('names', southMode ? base : ['all', base, selected]);
      map.setFilter('closed', ['all', scope, ['==', ['get', 'compare_category'], 'closed-south']]);
      map.setFilter('held', ['all', scope, ['==', ['get', 'compare_category'], 'held']]);
      map.setLayoutProperty('closed', 'visibility', side === 'right' && southMode && $('south').checked ? 'visible' : 'none');
      map.setLayoutProperty('held', 'visibility', side === 'right' && southMode && $('other-held').checked ? 'visible' : 'none');
    }
    right.setPaintProperty('trails', 'line-color', southMode ? '#c02d91' : ['get', $('suggestions').checked ? 'compare_suggested_color' : 'compare_color']);
    $('left-title').textContent = southMode ? 'Current rough trail geometry · cyan' : 'Current site · saved geometry & colors';
    $('right-title').textContent = southMode ? 'Reviewed GIS · magenta / Closed south · dashed amber' : $('suggestions').checked ? 'New GIS · suggested color aliases' : 'New GIS · unchanged color lookup';
  }
  function showCase() {
    selectedCase = report.cases.find(c => c.id === $('case').value);
    if (!selectedCase) return;
    activeKey = selectedCase.id;
    $('title').textContent = selectedCase.name;
    $('kind').textContent = selectedCase.analysis.kind;
    $('explanation').textContent = selectedCase.analysis.explanation;
    $('recommendation').textContent = selectedCase.analysis.recommendation;
    $('vintage').textContent = `GIS Comments: ${selectedCase.raw_attributes.Comments || 'not supplied'}. GIS edit date: ${selectedCase.edit_date || 'unknown'}. These are record metadata, not proof of a reroute or repaint date. ${$('park').value === 'walnut-creek' ? report.evidence.sources.walnut.finding : ''}`;
    $('swatches').replaceChildren();
    const seen = new Set();
    for (const r of selectedCase.old_records) if (!seen.has(r.name)) { swatch(`Current: ${r.name}`, r.color); seen.add(r.name); }
    swatch(`Raw GIS name: ${selectedCase.name}`, selectedCase.raw_color);
    if (selectedCase.suggested_color) swatch('Suggested: preserve the established route color', selectedCase.suggested_color);
    links(selectedCase.analysis.sources);
    $('raw').textContent = JSON.stringify({source_id: selectedCase.id, GIS: selectedCase.raw_attributes, current_records: selectedCase.old_records, matches: selectedCase.matches.map(m => ({current_id: m.existing_id, name: m.existing_name, source_coverage: m.source_coverage, current_coverage: m.existing_coverage}))}, null, 2);
    setDecisions([['', 'Not decided'], ['suggested-alias', 'Use suggested color alias'], ['preserve-current', 'Preserve current color'], ['gis-name-color', 'Use the GIS name’s color'], ['discuss', 'Discuss this segment']]);
    // An unsupported alias is never offered as a ready-made decision.
    if (!selectedCase.suggested_color) $('decision').querySelector('[value="suggested-alias"]').disabled = true;
    renderLayers(); fit(selectedCase.bounds);
  }
  function changePark() {
    const southMode = $('park').value === 'biscuit-run';
    $('color-controls').hidden = southMode; $('south-controls').hidden = !southMode; $('maps').hidden = $('park').value !== 'ivy-creek-natural-area';
    if (!southMode) {
      $('case').replaceChildren();
      const cases = report.cases.filter(c => c.park_id === $('park').value);
      for (const [i, c] of cases.entries()) { const o = document.createElement('option'); o.value = c.id; o.textContent = `${i + 1}/${cases.length} · ${c.name} · ${c.analysis.kind}`; $('case').append(o); }
      showCase(); return;
    }
    selectedCase = null; activeKey = 'biscuit-south';
    $('title').textContent = 'Southern 400 acres'; $('kind').textContent = 'Better geometry reference · access explicitly Closed';
    $('explanation').textContent = report.south.note;
    $('recommendation').textContent = report.south.proposed_use;
    $('vintage').textContent = report.evidence.sources.biscuit.finding;
    $('swatches').replaceChildren(); swatch('Current rough lines from the saved map', '#008fa8'); swatch('Geometry you reviewed as good', '#c02d91'); swatch('46 southern GIS lines · Closed', '#a95713');
    links(['biscuit']); $('raw').textContent = JSON.stringify(report.south, null, 2);
    setDecisions([['', 'Not decided'], ['closed-geometry', 'Use southern geometry with Closed status'], ['reference-only', 'Keep southern geometry as reference'], ['discuss', 'Discuss access / status evidence']]);
    renderLayers(); fit(report.parks.find(p => p.id === 'biscuit-run').bounds);
  }
  $('case').onchange = showCase; $('park').onchange = changePark;
  $('next').onclick = () => { $('case').selectedIndex = ($('case').selectedIndex + 1) % $('case').options.length; showCase(); };
  $('previous').onclick = () => { $('case').selectedIndex = ($('case').selectedIndex + $('case').options.length - 1) % $('case').options.length; showCase(); };
  for (const id of ['suggestions', 'context', 'south', 'other-held']) $(id).onchange = renderLayers;
  $('whole-park').onclick = () => fit(report.parks.find(p => p.id === $('park').value).bounds);
  $('south-extent').onclick = () => fit(report.south.bounds);
  $('export').onclick = () => {
    const value = {schema_version: 1, kind: report.kind, review_hash: report.review_hash, parent_review_hash: report.parent_review_hash,
      source_hash: report.source_hash, baseline_hash: report.baseline_hash, geometry_feedback_hash: report.feedback_hash,
      publication_authorized: false, exported_at: new Date().toISOString(), questions: state.questions};
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = 'albemarle-color-and-south-feedback.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  changePark(); window.__followupReady = true;
})().catch(error => { document.getElementById('status').textContent = `Comparison could not load: ${error.message}`; console.error(error); });
