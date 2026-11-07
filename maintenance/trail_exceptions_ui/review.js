const $ = (id) => document.getElementById(id);
const [report,incoming,existing,official,preview] = await Promise.all(['exceptions.json','incoming.geojson','existing.geojson','official-at.geojson','preview.json'].map(async (url) => {const r=await fetch(url);if(!r.ok)throw new Error(`Could not load ${url}`);return r.json();}));
const confirmedResponse = await fetch('confirmed-decisions.json');
const confirmed = confirmedResponse.ok ? await confirmedResponse.json() : null;
if (confirmed && (confirmed.review_hash !== report.review_hash || confirmed.acceptance_hash !== report.acceptance_hash)) throw new Error('Confirmed source choices belong to another review');
const locked = confirmed?.decisions || {};
const accessResponse=await fetch('access-decisions.json');
const accessReceipt=accessResponse.ok?await accessResponse.json():null;
if(accessReceipt&&(accessReceipt.review_hash!==report.review_hash||accessReceipt.acceptance_hash!==report.acceptance_hash))throw new Error('Access decisions belong to another review');
const accessDecisions=new Map((accessReceipt?.rows||[]).map((r)=>[r.id,r]));
const accessLabels={approve:'Access approved',reject:'Rejected',hold:'Held: contrary evidence'};
const rows = new Map(report.rows.map((r) => [r.id,r]));
const features = new Map(incoming.features.map((f) => [f.id,f]));
const storageKey = `trail-source-exceptions:${report.review_hash}`;
let saved={};try{saved=JSON.parse(localStorage.getItem(storageKey)||'{}');}catch{}
const decisions=Object.fromEntries(report.rows.filter((r)=>r.options.length).map((r)=>[r.id,r.options.includes(saved.decisions?.[r.id])?saved.decisions[r.id]:'pending']));
Object.assign(decisions, locked);
for(const id of accessDecisions.keys())decisions[id]='hold';
const notes=saved.notes||{};
let selected=null;
function persist(){try{localStorage.setItem(storageKey,JSON.stringify({decisions,notes}));$('saved').textContent='Saved in this browser. Export to return your choices.';}catch{$('saved').textContent='Export to save your choices.';}}
function text(tag,value,parent,cls){const e=document.createElement(tag);e.textContent=value;if(cls)e.className=cls;parent.append(e);return e;}
function link(parent,label,url){const a=text('a',label,parent);a.href=url;a.target='_blank';a.rel='noopener';return a;}
const categories={appalachian:'Appalachian Trail — NPS / ATC',patc:'Tuscarora / Massanutten — PATC vs USFS','state-parks':'State parks — DCR vs USFS','at-junctions':'AT approaches and junctions','same-source':'Overlaps within the USFS feed',access:'Access / geometry holds',resolved:'Sandy Gap — already resolved'};
for(const [value,label] of Object.entries(categories)){const option=text('option',`${label} (${report.summary[value]||0}${report.rows.filter((r)=>r.category===value&&locked[r.id]).length?' — confirmed':''})`,$('category'));option.value=value;}
$('summary').textContent=accessReceipt?`All source preferences confirmed. Access: ${accessReceipt.counts.approve} approved, ${accessReceipt.counts.reject} rejected, ${accessReceipt.counts.hold} held. Publication remains pending.`:`${report.accepted_count} accepted additions are fixed. ${report.rows.filter((r)=>r.options.length&&!locked[r.id]).length} unresolved records remain; AT source choices already confirmed. Preferences do not change map geometry.`;
$('rejected').textContent=`${report.rejected.length} additional source records have no usable geometry and remain rejected. See the full evidence file for their names and IDs.`;
for(const source of report.sources.sources){const div=document.createElement('div');div.className='source-evidence';text('strong',source.name,div);text('p',source.authority,div);text('p',source.updates,div);text('p',source.limitations,div);link(div,'Official source / steward',source.url);if(source.evidence_url){text('span',' · ',div);link(div,'Update / provenance evidence',source.evidence_url);}$('sources').append(div);}
for(const value of report.limitations)text('li',value,$('limitations'));
mapboxgl.accessToken=preview.public_token;
const maps=['before','after'].map((container)=>new mapboxgl.Map({container,style:'style.json',center:[-79.6,37.8],zoom:9}));
window.exceptionMaps=maps;
let syncing=false;
for(const [i,map] of maps.entries()){
  map.addControl(new mapboxgl.NavigationControl(),'bottom-right');
  new ResizeObserver(()=>map.resize()).observe(map.getContainer());
  map.on('move',()=>{if(syncing)return;syncing=true;maps[1-i].jumpTo({center:map.getCenter(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch(),padding:map.getPadding()});syncing=false;});
}
await Promise.all(maps.map((m)=>new Promise((resolve)=>m.on('load',resolve))));
const ids=(values)=>['in',['get','review_id'],['literal',values]];
for(const [i,map] of maps.entries()){
  map.addSource('incoming',{type:'geojson',data:incoming,promoteId:'review_id'});
  map.addSource('existing',{type:'geojson',data:existing,promoteId:'review_id'});
  map.addSource('official',{type:'geojson',data:official,promoteId:'review_id'});
  map.addLayer({id:'accepted-lines',type:'line',source:'incoming',filter:['==',['get','accepted'],true],paint:{'line-color':['get','map_color'],'line-width':3,'line-opacity':.8}});
  map.addLayer({id:'official-at',type:'line',source:'official',filter:ids([]),paint:{'line-color':'#7144d2','line-width':3,'line-opacity':.8}});
  map.addLayer({id:'captured-existing',type:'line',source:'existing',filter:ids([]),paint:{'line-color':'#f28a18','line-width':6,'line-opacity':.7}});
  if(i===1){
    map.addLayer({id:'peers',type:'line',source:'incoming',filter:ids([]),paint:{'line-color':'#07899b','line-width':4,'line-dasharray':[2,2]}});
    map.addLayer({id:'selected-incoming',type:'line',source:'incoming',filter:ids([]),paint:{'line-color':'#cf008b','line-width':3}});
  }
}
function visible(){const category=$('category').value,q=$('search').value.toLowerCase();return report.rows.filter((r)=>r.category===category&&($('outcome').value==='all'||category!=='access'||accessDecisions.get(r.id)?.action===$('outcome').value)&&`${r.name} ${r.source_attributes.trail_no||''} ${r.id}`.toLowerCase().includes(q));}
function list(){const shown=visible();$('count').textContent=`${shown.length} records shown · ${shown.filter((r)=>decisions[r.id]&&decisions[r.id]!=='pending').length} choices recorded`;$('records').replaceChildren();for(const r of shown){const b=document.createElement('button');b.className=`record${r.id===selected?' active':''}`;b.dataset.id=r.id;text('span',`${r.name} · ${(r.length_m/1609.344).toFixed(2)} mi`,b);text('small',accessDecisions.has(r.id)?accessLabels[accessDecisions.get(r.id).action]:locked[r.id]?'Confirmed: '+report.actions[locked[r.id]]:r.options.length?report.actions[decisions[r.id]]:'Already accepted: TNC route',b);b.onclick=()=>select(r.id);$('records').append(b);}}
function paint(){const row=rows.get(selected);for(const [i,map] of maps.entries()){
  map.setLayoutProperty('accepted-lines','visibility',$('accepted').checked?'visible':'none');
  map.setFilter('official-at',ids($('official').checked&&row?row.official_at_ids:[]));
  map.setFilter('captured-existing',ids(row?row.matches.map((m)=>m.id):[]));
  if(i===1){map.setFilter('peers',ids($('peers').checked&&row?row.peers.map((p)=>p.id):[]));map.setFilter('selected-incoming',ids(row?[row.id]:[]));}
}}
function fit(){const r=rows.get(selected);if(r)maps[0].fitBounds([r.bounds.slice(0,2),r.bounds.slice(2)],{padding:45,duration:0,maxZoom:17,retainPadding:false});}
function select(id,zoom=true){
  selected=id;const row=rows.get(id),detail=$('detail');detail.replaceChildren();
  text('h2',row.name,detail);
  const access=accessDecisions.get(id);
  if(access){text('p',`${accessLabels[access.action]}: ${access.reason}. ${access.geometry_use==='source-replacement'?'Accepted as a source replacement, not an overlapping addition.':''}`,detail,'recommendation');
    if(access.connectivity)text('p',`Short-component check: ${access.connectivity.component_ids.length} segment(s), ${access.connectivity.reference_count} useful reference(s), ${access.connectivity.tolerance_m} m endpoint tolerance. ${[...new Set(access.connectivity.contacts.map((c)=>c.reference_name))].join(', ')||'No useful connections found'}.`,detail);
  } else text('p',`${row.recommendation_title}. Recommendation: ${report.actions[row.recommendation]}. ${row.explanation}`,detail,'recommendation');
  text('p',`Original hold: ${row.reason}. Existing coverage within 3 / 20 m: ${Math.round(row.coverage['3']*100)}% / ${Math.round(row.coverage['20']*100)}%. Official AT coverage within 3 / 20 m: ${Math.round(row.official_at_coverage['3']*100)}% / ${Math.round(row.official_at_coverage['20']*100)}%.`,detail);
  link(detail,'USFS source record service',row.source_url);
  const p=row.source_attributes;
  text('p',`Trail #${p.trail_no||'unknown'} · route ID ${p.trail_cn||'unknown'} · mileposts ${p.bmp??'?'}–${p.emp??'?'}. The current source supplies no blaze color or individual survey date.`,detail);
  if(row.matches.length){
    const d=document.createElement('details');text('summary',`Existing source evidence (${row.matches.length} matches)`,d);
    for(const m of row.matches){text('p',`${m.name} — ${m.source}, ${Math.round(m.coverage_20m*100)}% coverage. ${Object.entries(m.provenance).map(([k,v])=>`${k}: ${v}`).join('; ')}`,d);}detail.append(d);
  }
  if(row.peers.length){
    const d=document.createElement('details');d.open=row.category==='same-source';text('summary',`Related incoming records (${row.peers.length})`,d);
    for(const peer of row.peers){text('p',`${peer.name} · trail #${peer.trail_no||'?'} · route ${peer.trail_cn||'?'} · mileposts ${peer.bmp??'?'}–${peer.emp??'?'} · ${peer.accepted?'ALREADY ACCEPTED':peer.status}. Shared coverage within 3 m: ${Math.round(peer.coverage_3m*100)}% of selected / ${Math.round(peer.reverse_3m*100)}% of other.`,d);const b=text('button','Compare this record',d);b.onclick=()=>{if(rows.has(peer.id)){ $('category').value=rows.get(peer.id).category;$('search').value='';select(peer.id);}else{const b=features.get(peer.id).geometry;const bounds=new mapboxgl.LngLatBounds();const walk=(c)=>{if(typeof c[0]==='number')bounds.extend(c);else c.forEach(walk);};walk(b.coordinates);maps[0].fitBounds(bounds,{padding:45,duration:0,retainPadding:false});}};}detail.append(d);
  }
  if(row.options.length&&!access){const label=text('label','Source preference',detail);const s=document.createElement('select');s.id='decision';for(const action of ['pending',...row.options]){const option=text('option',report.actions[action],s);option.value=action;}s.value=decisions[id];s.disabled=Boolean(locked[id]);s.onchange=()=>{decisions[id]=s.value;persist();list();};label.append(s);const l=text('label','Notes / requested resolution',detail),n=document.createElement('textarea');n.id='note';n.value=notes[id]||'';n.oninput=()=>{notes[id]=n.value;persist();};l.append(n);}
  else if(!access) text('p','TNC Sandy Gap east and west are already accepted. This alternate cannot change that approval in this review.',detail);
  list();paint();if(zoom)fit();
}
function change(){const first=visible()[0];if(first)select(first.id);else{selected=null;$('detail').replaceChildren();list();paint();}}
$('category').onchange=change;$('outcome').onchange=change;$('search').oninput=change;$('fit').onclick=fit;
for(const id of ['official','accepted','peers'])$(id).onchange=paint;
$('recommend').onclick=()=>{for(const row of visible())if(!locked[row.id]&&!accessDecisions.has(row.id)&&row.options.includes(row.recommendation))decisions[row.id]=row.recommendation;persist();if(selected)select(selected,false);};
$('export').onclick=()=>{const value={schema_version:1,kind:report.kind,review_hash:report.review_hash,acceptance_hash:report.acceptance_hash,confirmed_hash:confirmed?.decision_hash||null,access_hash:accessReceipt?.decision_hash||null,exported_at:new Date().toISOString(),decisions,notes};const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='tnc-usfs-source-choices.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
if(accessReceipt){$('category').value='access';$('outcome').value='hold';$('recommend').disabled=true;}
else if (locked[report.rows.find((r)=>r.category==='appalachian')?.id]) $('category').value='patc';
change();window.exceptionReviewReady=true;
