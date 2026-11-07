/* Saved source and inventory overlays; no publication requests. */
(async () => {
  const $ = id => document.getElementById(id);
  const [report, source, existing, references, config] = await Promise.all(
    ['review.json', 'source.geojson', 'existing.geojson', 'references.geojson', 'preview.json'].map(async url => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Cannot load ${url}`);
      return response.json();
    })
  );
  window.__albemarleReport = report;
  const key = `albemarle-validation:${report.review_hash}`;
  let state = {parks: {}, features: {}, notes: ''};
  try { state = JSON.parse(localStorage.getItem(key)) || state; } catch { /* New review. */ }
  const save = () => {
    try { localStorage.setItem(key, JSON.stringify(state)); $('save-status').textContent = 'Feedback saved in this browser. Export to keep a durable copy.'; }
    catch { $('save-status').textContent = 'Browser storage unavailable. Export feedback before closing.'; }
  };
  const c = report.counts;
  $('summary').textContent = `${c.existing_preserved} current trails preserved · ${c.eligible} eligible GIS records · ${c.held} held. ${c.existing_coverage_gaps} current records have coverage gaps; ${c.color_conflicts} source records have potential color conflicts.`;
  $('method').textContent = `${report.method.identity_suggestion} ${report.method.limitations} Other uploaded tilesets without editable datasets were not compared: ${report.uncompared_tilesets.join(', ') || 'none'}.`;
  for (const park of report.parks) {
    const option = document.createElement('option'); option.value = park.id;
    option.textContent = `${park.name} (${park.existing_count} current / ${park.source_counts.eligible || 0} eligible)`;
    $('parks').append(option);
  }
  $('notes').value = state.notes;
  $('notes').oninput = () => { state.notes = $('notes').value; save(); };
  mapboxgl.accessToken = config.public_token;
  const map = window.__albemarleMap = new mapboxgl.Map({container: 'map', style: 'mapbox://styles/mapbox/outdoors-v12', center: [-78.55, 38.06], zoom: 10});
  map.addControl(new mapboxgl.NavigationControl(), 'top-right');
  const sourceById = new Map(source.features.map(f => [f.id, f]));
  const oldById = new Map(existing.features.map(f => [f.id, f]));
  const refById = new Map(references.features.map(f => [f.id, f]));
  const rowById = new Map(report.rows.map(r => [r.id, r]));
  const oldRowById = new Map(report.existing_rows.map(r => [r.id, r]));
  const fit = features => {
    const bounds = new mapboxgl.LngLatBounds();
    const visit = coords => { if (typeof coords[0] === 'number') bounds.extend(coords.slice(0, 2)); else coords.forEach(visit); };
    features.filter(Boolean).forEach(f => visit(f.geometry.coordinates));
    if (!bounds.isEmpty()) map.fitBounds(bounds, {padding: innerWidth > 680 ? {left: 425, right: 65, top: 50, bottom: 50} : {top: innerHeight * .46, bottom: 35, left: 25, right: 25}, maxZoom: 17, duration: 0});
  };
  const attention = r => r.category === 'eligible' && (r.comparison !== 'one-to-one-suggestion' || r.color_conflict || r.duplicate_candidates?.length || r.other_overlaps.length || r.matches.some(m => m.conflicts.length));
  function rows() {
    const park = $('parks').value, mode = $('filter').value, query = $('search').value.toLowerCase();
    let values = mode === 'existing' ? report.existing_rows : mode === 'attention' ? [...report.rows.filter(attention), ...report.existing_rows.filter(r => r.comparison !== 'covered-needs-review')] : report.rows.filter(r => r.category === mode);
    values = values.filter(r => (!park || r.park_id === park) && (!query || `${r.name} ${r.location} ${r.id}`.toLowerCase().includes(query)));
    $('rows').replaceChildren(); $('row-count').textContent = `${values.length} records`;
    for (const r of values) {
      const li = document.createElement('li'), button = document.createElement('button'), meta = document.createElement('div');
      button.textContent = `${oldRowById.has(r.id) ? 'Current: ' : ''}${r.name || '(unnamed)'}`;
      button.onclick = () => show(r.id); meta.className = 'muted';
      meta.textContent = `${r.location} · ${r.comparison}${r.color_conflict ? ' · COLOR CONFLICT' : ''}`;
      li.append(button, meta); $('rows').append(li);
    }
  }
  function show(id) {
    const r = rowById.get(id) || oldRowById.get(id), isOld = oldRowById.has(id);
    if (r.category === 'held') {
      $('held').checked = true; map.setLayoutProperty('held-lines', 'visibility', 'visible');
    }
    const related = isOld ? r.matches.map(fid => sourceById.get(fid)) : r.matches.map(m => oldById.get(m.existing_id));
    const f = (isOld ? oldById : sourceById).get(id);
    const context = isOld ? [] : r.other_overlaps.map(m => refById.get(m.key));
    fit([f, ...related]);
    map.getSource('selected').setData({type: 'FeatureCollection', features: [f, ...related, ...context].filter(Boolean)});
    $('detail').hidden = false; $('detail').replaceChildren();
    const heading = document.createElement('h2'); heading.textContent = `${isOld ? 'Current: ' : 'Source: '}${r.name || '(unnamed)'}`;
    const data = document.createElement('pre');
    const lines = [id, `${r.location} · ${r.comparison}`];
    if (isOld) {
      lines.push(`Covered by eligible GIS within 3m / 10m: ${(r.eligible_coverage['3'] * 100).toFixed(1)}% / ${(r.eligible_coverage['10'] * 100).toFixed(1)}%`, 'Current feature is preserved.');
      for (const fid of r.matches) { const m = rowById.get(fid); lines.push(`${m.category}: ${m.name} (${m.id})`); }
    } else {
      lines.push(`Status: ${r.status} · Ownership: ${r.ownership} · Access: ${r.access}`, ...r.reasons);
      if (!r.matches.length) lines.push('No substantial match to current County geometry.');
      for (const m of r.matches) {
        lines.push(`\nCurrent: ${m.existing_name} (${m.existing_id})`, `Within 3m — source covered: ${(m.source_coverage['3'] * 100).toFixed(1)}%; current covered: ${(m.existing_coverage['3'] * 100).toFixed(1)}%`);
        for (const conflict of m.conflicts) lines.push(`${conflict.property}: ${JSON.stringify(conflict.existing)} → ${JSON.stringify(conflict.source)}`);
      }
      if (r.duplicate_candidates?.length) lines.push(`Possible duplicate GIS records: ${r.duplicate_candidates.join(', ')}`);
      for (const m of r.other_overlaps) lines.push(`Other dataset: ${m.dataset_name}${m.protected ? ' (protected)' : ''}; ${(m.source_coverage['10'] * 100).toFixed(1)}% source coverage within 10m`);
    }
    data.textContent = lines.join('\n');
    const label = document.createElement('label'); label.textContent = 'Feature feedback';
    const choice = document.createElement('select'); choice.id = 'feature-decision';
    for (const [value, title] of [['', 'Not reviewed'], ['investigate', 'Investigate conflict'], ['keep-existing', 'Keep current geometry'], ['reviewed', 'Reviewed for next proposal']]) {
      const option = document.createElement('option'); option.value = value; option.textContent = title; choice.append(option);
    }
    const notes = document.createElement('textarea'); notes.id = 'feature-notes'; notes.rows = 2; notes.setAttribute('aria-label', 'Feature notes');
    choice.value = state.features[id]?.decision || ''; notes.value = state.features[id]?.notes || '';
    choice.onchange = notes.oninput = () => { state.features[id] = {decision: choice.value, notes: notes.value}; save(); };
    const close = document.createElement('button'); close.textContent = 'Close detail'; close.onclick = () => { $('detail').hidden = true; map.getSource('selected').setData({type: 'FeatureCollection', features: []}); };
    label.htmlFor = choice.id; $('detail').append(heading, data, label, choice, notes, close);
  }
  function filters() {
    const park = $('parks').value;
    const scope = park ? ['==', ['get', 'review_park'], park] : ['literal', true];
    map.setFilter('current-lines', scope);
    map.setFilter('eligible-lines', ['all', scope, ['==', ['get', 'review_category'], 'eligible']]);
    map.setFilter('held-lines', ['all', scope, ['==', ['get', 'review_category'], 'held']]);
  }
  function parkChanged() {
    const park = report.parks.find(p => p.id === $('parks').value);
    $('park-summary').textContent = park ? `${park.existing_count} current · ${park.source_counts.eligible || 0} eligible · ${park.source_counts.held || 0} held · ${park.coverage_gaps} current coverage gaps · ${park.color_conflicts} potential color conflicts.` : 'Select a park to review matching geometry and save park feedback.';
    $('park-decision').disabled = $('park-notes').disabled = !park;
    $('park-decision').value = state.parks[park?.id]?.decision || '';
    $('park-notes').value = state.parks[park?.id]?.notes || '';
    $('detail').hidden = true;
    map.getSource('selected').setData({type: 'FeatureCollection', features: []});
    filters(); rows();
    fit([...source.features.filter(f => f.properties.review_category === 'eligible'), ...existing.features].filter(f => !park || f.properties.review_park === park.id));
    if (park && !source.features.some(f => f.properties.review_park === park.id && f.properties.review_category === 'eligible') && !existing.features.some(f => f.properties.review_park === park.id)) fit(source.features.filter(f => f.properties.review_park === park.id));
  }
  $('park-decision').onchange = $('park-notes').oninput = () => {
    state.parks[$('parks').value] = {decision: $('park-decision').value, notes: $('park-notes').value}; save();
  };
  $('filter').onchange = $('search').oninput = rows;
  $('export').onclick = () => {
    const exported = {schema_version: 1, kind: report.kind, review_hash: report.review_hash, source_hash: report.source_hash,
      baseline_hash: report.baseline_hash, style_hash: report.style_hash, policy_hash: report.policy_hash,
      publication_authorized: false, exported_at: new Date().toISOString(), ...state};
    const url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'albemarle-validation-feedback.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  map.on('load', () => {
    for (const [id, data] of [['current', existing], ['source', source], ['references', references], ['selected', {type: 'FeatureCollection', features: []}]]) map.addSource(id, {type: 'geojson', data});
    map.addLayer({id: 'reference-lines', type: 'line', source: 'references', paint: {'line-color': ['case', ['get', 'review_protected'], '#17743b', '#56606a'], 'line-width': 3, 'line-opacity': .65}});
    map.addLayer({id: 'current-lines', type: 'line', source: 'current', paint: {'line-color': '#008fa8', 'line-width': 7, 'line-opacity': .65}});
    map.addLayer({id: 'eligible-lines', type: 'line', source: 'source', paint: {'line-color': '#c02d91', 'line-width': 3}});
    map.addLayer({id: 'held-lines', type: 'line', source: 'source', layout: {visibility: 'none'}, paint: {'line-color': '#be3028', 'line-width': 3, 'line-dasharray': [2, 2]}});
    map.addLayer({id: 'selection-lines', type: 'line', source: 'selected', paint: {'line-color': '#f6b600', 'line-width': 12, 'line-opacity': .28}}, 'current-lines');
    for (const [control, layer] of [['existing', 'current-lines'], ['eligible', 'eligible-lines'], ['held', 'held-lines'], ['references', 'reference-lines']]) $(control).onchange = () => map.setLayoutProperty(layer, 'visibility', $(control).checked ? 'visible' : 'none');
    $('colors').onchange = () => {
      map.setPaintProperty('current-lines', 'line-color', $('colors').checked ? ['get', 'review_color'] : '#008fa8');
      map.setPaintProperty('eligible-lines', 'line-color', $('colors').checked ? ['get', 'review_color'] : '#c02d91');
    };
    $('parks').onchange = parkChanged;
    $('overview').onclick = () => { $('parks').value = ''; parkChanged(); };
    $('next').onclick = () => { const options = $('parks').options; $('parks').selectedIndex = ($('parks').selectedIndex + 1) % options.length; parkChanged(); };
    map.on('click', event => {
      const features = map.queryRenderedFeatures(event.point, {layers: ['eligible-lines', 'held-lines', 'current-lines']});
      if (features.length) show(features[0].properties.review_id);
    });
    parkChanged(); window.__albemarleReady = true;
  });
})().catch(error => { document.getElementById('summary').textContent = `Review failed to load: ${error.message}`; console.error(error); });
