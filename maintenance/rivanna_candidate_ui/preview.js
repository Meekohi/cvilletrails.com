'use strict';
(async () => {
  const response = await fetch('preview.json');
  if (!response.ok) throw new Error('Could not load the reviewed proposal');
  const data = await response.json();
  mapboxgl.accessToken = data.public_token;
  const map = new mapboxgl.Map({container:'map',style:data.style,center:[-78.49,38.035],zoom:11.5});
  map.addControl(new mapboxgl.NavigationControl());
  const byId = new Map(data.candidate.features.map(f => [f.id, f]));
  const actions = data.actions.filter(a => ['add_official_road_walk','mark_existing_route_temporarily_closed','retain_existing_primary_detour'].includes(a.action));
  const points = geometry => geometry.type === 'LineString' ? geometry.coordinates : geometry.coordinates.flat();
  function fit(features) {
    const bounds = new mapboxgl.LngLatBounds();
    features.forEach(f => points(f.geometry).forEach(p => bounds.extend(p)));
    map.fitBounds(bounds,{padding:{top:45,right:45,bottom:window.innerWidth<650?150:210,left:45},maxZoom:16,duration:450});
  }
  function select(feature, action) {
    document.querySelector('#name').textContent = feature.properties.section || feature.properties.Name;
    document.querySelector('#description').textContent = feature.properties.access_status === 'temporarily-closed'
      ? 'Temporarily closed. The entire existing Fontaine segment is shown in red; use the green detour.'
      : action?.action === 'add_official_road_walk' ? 'Official road walk included as part of the primary route.'
      : action?.action === 'retain_existing_primary_detour' ? 'Existing Fontaine detour retained and shown as an active route.'
      : 'Existing Rivanna route retained.';
    document.querySelector('#note').textContent = action?.review_note ? `Your note: ${action.review_note}` : '';
    document.querySelectorAll('#routes button').forEach(b => b.setAttribute('aria-pressed',String(b.dataset.id === feature.id)));
    fit([feature]);
  }
  for (const action of actions) {
    const feature = byId.get(action.proposed_feature_id || action.current_feature_id);
    const button = document.createElement('button');
    button.dataset.id = feature.id;
    button.setAttribute('aria-pressed','false');
    button.textContent = feature.properties.section;
    const caption = document.createElement('small');
    caption.textContent = action.action === 'add_official_road_walk' ? 'Add road walk' : action.action === 'mark_existing_route_temporarily_closed' ? 'Temporarily closed · red' : 'Retain active detour';
    button.append(caption);
    button.addEventListener('click',() => select(feature,action));
    document.querySelector('#routes').append(button);
  }
  document.querySelector('#overview').addEventListener('click',() => fit(data.candidate.features));
  map.on('load',() => {
    document.querySelector('#status').textContent = '72 features · 7 additions · 1 closure marking · no deletions';
    const closure = actions.find(a => a.action === 'mark_existing_route_temporarily_closed');
    select(byId.get(closure.current_feature_id),closure);
  });
  map.on('click','rivanna-trail',event => {
    const displayed = event.features[0];
    // Vector/GeoJSON renderers may not retain string IDs; section is only used
    // to locate the full candidate for this local preview, never for ingestion.
    const feature = byId.get(displayed.id) || data.candidate.features.find(f => f.properties.section === displayed.properties.section);
    if (feature) select(feature,actions.find(a => (a.proposed_feature_id || a.current_feature_id) === feature.id));
  });
  map.on('mouseenter','rivanna-trail',() => {map.getCanvas().style.cursor='pointer';});
  map.on('mouseleave','rivanna-trail',() => {map.getCanvas().style.cursor='';});
  map.on('error',() => {document.querySelector('#status').textContent = 'A map resource failed to load. Reload if trails or the basemap are missing.';});
})().catch(error => {document.querySelector('#status').textContent=error.message;});
