import { activeUpdates, visibleUpdates, featureName, safeLink, contextualSystem, systemForFeature } from './data.js';

const $ = id => document.getElementById(id);
const state = { systems: [], updates: [], mode: null, systemId: null, scope: 'map', loaded: false, updatesLoaded: false, position: null };
let map;
let returnFocus;
let statusTimer;
let contextSystem = null;
let displayedContextSystem = null;
let selectedSystem = null;
let titleTimer;

function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (className) el.className = className;
  return el;
}

function status(message, persistent = false) {
  clearTimeout(statusTimer);
  $('status').textContent = message;
  $('status').hidden = false;
  if (!persistent) statusTimer = setTimeout(() => { $('status').hidden = true; }, 7000);
}

function openPanel(mode, title, focus = true) {
  if ($('panel').hidden) returnFocus = document.activeElement;
  const replacingFocusedContent = $('panel-content').contains(document.activeElement);
  state.mode = mode;
  $('panel').hidden = false;
  $('panel').classList.toggle('is-changing', mode !== 'updates' && document.querySelector('.brand-copy').classList.contains('is-changing'));
  $('panel-title').textContent = title;
  $('panel-kicker').textContent = mode === 'updates' ? 'BEFORE YOUR NEXT TURN' : 'OUT ON THE TRAILS';
  $('map-title').setAttribute('aria-expanded', String(mode !== 'updates'));
  $('updates').setAttribute('aria-expanded', String(mode === 'updates'));
  $('panel-content').replaceChildren();
  $('panel-content').scrollTop = 0;
  if (focus || replacingFocusedContent) $('close-panel').focus({ preventScroll: true });
}

function closePanel() {
  $('panel').hidden = true;
  $('panel').classList.remove('is-changing');
  state.mode = null;
  $('map-title').setAttribute('aria-expanded', 'false');
  $('updates').setAttribute('aria-expanded', 'false');
  returnFocus?.focus({ preventScroll: true });
}

function sourceLink(url, title) {
  const link = element('a', title, 'source-link');
  const href = safeLink(url);
  if (href) { link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
  return link;
}

function refreshContext() {
  if (!map || !map.isStyleLoaded()) return;
  const b = map.getBounds();
  const center = map.project(map.getCenter());
  const nearby = map.queryRenderedFeatures([[center.x - 60, center.y - 60], [center.x + 60, center.y + 60]])
    .filter(feature => feature.layer.type === 'line').map(feature => feature.sourceLayer);
  const next = selectedSystem || contextualSystem(state.systems, [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], map.getZoom(), nearby, contextSystem?.id);
  if (next?.id === contextSystem?.id) return;
  contextSystem = next;
  clearTimeout(titleTimer);
  const copy = document.querySelector('.brand-copy');
  const update = () => {
    const title = contextSystem?.context_title || contextSystem?.name || 'Cville Trails';
    $('map-title-text').textContent = title;
    $('map-subtitle').textContent = contextSystem ? 'Cville Trails · About these trails' : 'Charlottesville & Albemarle';
    $('map-title').setAttribute('aria-label', contextSystem ? `About ${title}` : 'About Cville Trails');
    displayedContextSystem = contextSystem;
    // Commit both views in the same frame, without reopening a closed panel or
    // replacing the user's Updates view. Automatic refreshes keep map focus.
    if (!$('panel').hidden && ['about', 'details'].includes(state.mode)) {
      if (displayedContextSystem) details(displayedContextSystem, null, false);
      else aboutMap(false);
    }
    copy.classList.remove('is-changing');
    $('panel').classList.remove('is-changing');
  };
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    update();
  } else {
    copy.classList.add('is-changing');
    $('panel').classList.toggle('is-changing', !$('panel').hidden && ['about', 'details'].includes(state.mode));
    titleTimer = setTimeout(update, 160);
  }
}

function aboutMap(focus = true) {
  state.systemId = null;
  openPanel('about', 'Cville Trails', focus);
  $('panel-content').append(element('p', 'Find your way around Charlottesville and Albemarle’s trail networks.'),
    element('p', 'Choose a trail system to zoom to it and see its details. You can also tap an individual trail. Use the location button to see where you are.'));
  const list = element('ul', null, 'system-list');
  for (const system of state.systems.filter(system => system.context_mode).sort((a, b) => a.name.localeCompare(b.name))) {
    const item = element('li');
    const button = element('button', system.name);
    button.type = 'button';
    button.onclick = () => zoomTo(system, true);
    item.append(button);
    list.append(item);
  }
  $('panel-content').append(element('h2', 'Explore trail systems'), list,
    element('p', 'Trail colors follow the curated map. Updates collect reviewed notices from trail managers.', 'hint'));
}

function zoomTo(system, showDetails = false) {
  if (!map) return;
  map.stop();
  const padding = { top: 90, bottom: 110, left: 35, right: 60 };
  if (showDetails) {
    // Keep the chosen network's overview identifiable even when its full extent
    // falls below the automatic context zoom or spans several smaller parks.
    selectedSystem = system;
    const panel = $('panel').getBoundingClientRect();
    if (matchMedia('(max-width: 600px)').matches) padding.bottom = innerHeight - panel.top + 16;
    else padding.left = panel.right + 24;
  } else closePanel();
  map.fitBounds(system.bounds, { padding, retainPadding: false, maxZoom: 15, duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 700 }, { trailSystemId: system.id });
}

function details(system, feature = null, focus = true) {
  state.systemId = system?.id;
  openPanel('details', feature ? featureName(feature.properties) : system.name, focus);
  const content = $('panel-content');
  if (feature && system) content.append(element('p', system.name, 'meta'));
  if (system) {
    if (system.map_note) content.append(element('p', system.map_note, 'map-note'));
    content.append(element('p', system.description));
    if (system.visitor_info?.length) {
      const facts = element('dl', null, 'visitor-info');
      for (const fact of system.visitor_info) facts.append(element('dt', fact.label), element('dd', fact.value));
      content.append(facts);
    }
    const sources = element('div', null, 'info-sources');
    for (const source of system.info_sources || [{url: system.url, label: system.source_label}]) {
      sources.append(sourceLink(source.url, `${source.label} ↗`));
    }
    content.append(sources);
    if (system.info_reviewed_on) content.append(element('p', `Official information checked ${new Date(system.info_reviewed_on + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'})}.`, 'meta'));
    const actions = element('div', null, 'actions');
    const show = element('button', 'Show on map', 'action'); show.onclick = () => zoomTo(system);
    const news = element('button', 'Trail updates', 'action'); news.onclick = () => showUpdates(system.id);
    actions.append(show, news); content.append(actions);
    const notices = visibleUpdates(activeUpdates(state.updates), state.systems, null, 'map', system.id);
    notices.forEach(item => content.append(notice(item)));
  } else {
    content.append(element('p', 'This trail is part of the curated map. More trail-system information is being added.'));
  }
  content.append(element('p', 'Trail colors follow the curated map. Check posted signs for current access and conditions.', 'hint'));
}

function notice(item) {
  const article = element('article', null, 'notice');
  article.append(element('span', item.kind.replaceAll('_', ' '), 'notice-kind'), element('h2', item.title), element('p', item.body));
  article.append(sourceLink(item.source_url, `${item.source_label} ↗`));
  article.append(element('p', `Reviewed ${new Date(item.reviewed_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`, 'meta'));
  return article;
}

function updateItems(systemId = null) {
  const bounds = map ? [map.getBounds().getWest(), map.getBounds().getSouth(), map.getBounds().getEast(), map.getBounds().getNorth()] : null;
  return visibleUpdates(activeUpdates(state.updates), state.systems, bounds, state.scope, systemId);
}

function renderUpdates() {
  const list = $('notice-list');
  if (!list) return;
  const items = updateItems(state.systemId);
  list.replaceChildren(...items.map(notice));
  if (!items.length) {
    const empty = element('div', null, 'empty');
    const symbol = element('span', '↟', 'empty-symbol'); symbol.setAttribute('aria-hidden', 'true');
    empty.append(symbol, element('h2', state.updatesLoaded ? 'No published updates here' : 'Updates are unavailable'), element('p', state.updatesLoaded ? 'Updates from trail managers will appear here after review. An empty feed does not mean every trail is open.' : 'The update feed could not be loaded. Check the trail manager’s website for current notices.'));
    list.append(empty);
  }
}

function showUpdates(systemId = null) {
  state.systemId = systemId;
  openPanel('updates', 'Trail updates');
  const content = $('panel-content');
  const label = element('label', 'Show updates for'); label.htmlFor = 'update-scope';
  const select = element('select'); select.id = 'update-scope';
  const options = [['map', 'This map area'], ['all', 'All trail systems'], ...state.systems.map(s => [s.id, s.name])];
  options.forEach(([value, title]) => { const option = element('option', title); option.value = value; select.append(option); });
  select.value = systemId || state.scope;
  select.onchange = () => {
    state.systemId = ['map', 'all'].includes(select.value) ? null : select.value;
    if (!state.systemId) state.scope = select.value;
    renderUpdates();
  };
  const list = element('div'); list.id = 'notice-list';
  content.append(label, select, element('p', 'Closures, access changes, and useful news from the people who care for these trails.', 'hint'), list);
  renderUpdates();
}

function refreshCount() {
  const bounds = map ? [map.getBounds().getWest(), map.getBounds().getSouth(), map.getBounds().getEast(), map.getBounds().getNorth()] : null;
  const count = visibleUpdates(activeUpdates(state.updates), state.systems, bounds, 'map').length;
  $('update-count').textContent = count;
  $('update-count').hidden = !count;
  $('updates').classList.toggle('has-updates', count > 0);
}

function initMap() {
  if (!window.mapboxgl || !mapboxgl.supported()) {
    status('The map could not start. Check your connection and browser support, then reload.', true); return;
  }
  mapboxgl.accessToken = 'pk.eyJ1IjoibWVla29oaSIsImEiOiJjaXhrbDl2eWwwMDIyMnFtb2ZndjM0NW14In0.U639AnCqXT1BNOyQtFYXIQ';
  map = new mapboxgl.Map({ container: 'map', style: 'mapbox://styles/meekohi/ckkolybrr6tjx17mjqflqw16b', center: [-78.482294, 38.031053], zoom: 12, hash: true, attributionControl: false });
  map.addControl(new mapboxgl.AttributionControl({ compact: true, customAttribution: '<a href="https://www.dcr.virginia.gov/state-parks/" target="_blank" rel="noopener">Virginia DCR trails</a>' }), 'bottom-right');
  const locate = new mapboxgl.GeolocateControl({ positionOptions: { enableHighAccuracy: true, timeout: 15000 }, trackUserLocation: true, showUserHeading: true });
  map.addControl(locate, 'top-right');
  map.addControl(new mapboxgl.NavigationControl({ showCompass: true, showZoom: true }), 'top-right');
  map.addControl(new mapboxgl.ScaleControl({ unit: 'imperial', maxWidth: 90 }), 'bottom-left');
  locate.on('geolocate', event => { state.position = event.coords; });
  locate.on('error', () => status('Unable to find your location. Check location permission and try the locate button again.'));
  map.on('movestart', event => {
    if (event.trailSystemId !== selectedSystem?.id) selectedSystem = null;
  });
  map.on('error', () => status('Some map data could not load. Check your connection if trails are missing.'));
  map.on('moveend', () => { refreshContext(); refreshCount(); if (state.mode === 'updates') renderUpdates(); });
  map.on('idle', refreshContext);
  map.on('click', event => {
    const layers = (map.getStyle()?.layers || []).filter(layer => layer.type === 'line' && /trail/i.test(layer.id) && !/fringe/i.test(layer.id)).map(layer => layer.id);
    if (!layers.length) return;
    const pad = 9;
    const features = map.queryRenderedFeatures([[event.point.x - pad, event.point.y - pad], [event.point.x + pad, event.point.y + pad]], { layers });
    const feature = features[0];
    if (!feature) return;
    const system = systemForFeature(state.systems, feature, [event.lngLat.lng, event.lngLat.lat]);
    details(system, feature);
  });
}

$('map-title').onclick = () => displayedContextSystem ? details(displayedContextSystem) : aboutMap();
$('updates').onclick = () => state.mode === 'updates' ? closePanel() : showUpdates();
$('close-panel').onclick = closePanel;
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('panel').hidden) closePanel(); });
$('report').onclick = () => {
  const coords = state.position;
  const location = coords ? ` at ${coords.latitude.toFixed(5)},${coords.longitude.toFixed(5)}` : '';
  const body = `Trail or park:\nWhat needs attention:\n\nMap view: ${window.location.href}`;
  $('report').href = `mailto:meekohi+trails@gmail.com?subject=${encodeURIComponent(`Trail issue${location}`)}&body=${encodeURIComponent(body)}`;
};

async function loadData() {
  await Promise.allSettled([
    fetch('data/systems.json').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(data => { state.systems = data; state.loaded = true; }),
    fetch('data/updates.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw Error(); return r.json(); }).then(data => { state.updates = data.updates; state.updatesLoaded = true; })
  ]);
  refreshCount();
  refreshContext();
  if (state.mode === 'about') aboutMap(false);
  if (state.mode === 'updates') renderUpdates();
}

if (document.readyState === 'complete') initMap(); else window.addEventListener('load', initMap, { once: true });
loadData();
setInterval(() => { refreshCount(); if (state.mode === 'updates') renderUpdates(); }, 60000);
