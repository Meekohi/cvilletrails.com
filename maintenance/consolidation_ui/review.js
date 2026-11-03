const $=id=>document.getElementById(id);
let data,map,ready=false;
let pickedPoints=[],pointMarkers=[];
const pointsStorageKey='cville-trails-preview-points';
function renderPoints(){
 $('coordinates').value=pickedPoints.map((p,i)=>`${i+1}. lat: ${p.lat.toFixed(6)}, lng: ${p.lng.toFixed(6)}`).join('\n');
 for(const id of ['copy-points','undo-point','clear-points'])$(id).disabled=!pickedPoints.length;
 pointMarkers.forEach(marker=>marker.remove());pointMarkers=[];
 if(map)for(const [i,p] of pickedPoints.entries()){
  const pin=document.createElement('div');pin.className='coordinate-pin';pin.textContent=String(i+1);pin.title=`Point ${i+1}: drag to adjust`;
  const marker=new mapboxgl.Marker({element:pin,draggable:true}).setLngLat([p.lng,p.lat]).addTo(map);
  marker.on('dragend',()=>{const position=marker.getLngLat();pickedPoints[i]={lat:position.lat,lng:position.lng};savePoints();});pointMarkers.push(marker);
 }
}
function savePoints(){try{localStorage.setItem(pointsStorageKey,JSON.stringify(pickedPoints));}catch{$('points-status').textContent='Browser storage unavailable; copy your points before closing.';}renderPoints();}
function setupPointPicker(){
 try{const saved=JSON.parse(localStorage.getItem(pointsStorageKey)||'[]');if(Array.isArray(saved))pickedPoints=saved.filter(p=>p&&Number.isFinite(p.lat)&&Number.isFinite(p.lng)&&Math.abs(p.lat)<=90&&Math.abs(p.lng)<=180);}catch{}
 $('pick-points').onchange=()=>{if(map)map.getCanvas().style.cursor=$('pick-points').checked?'crosshair':'';};
 $('undo-point').onclick=()=>{pickedPoints.pop();savePoints();};$('clear-points').onclick=()=>{pickedPoints=[];savePoints();};
 $('copy-points').onclick=async()=>{try{await navigator.clipboard.writeText($('coordinates').value);$('points-status').textContent='Copied — paste these points into chat.';}catch{$('coordinates').focus();$('coordinates').select();$('points-status').textContent='Coordinates selected. Copy them and paste into chat.';}};
 renderPoints();
}
const descriptions={
 'ivy-creek-natural-area':'County remains the park source. The 66 overlapping City additions are excluded.',
 'ragged-mountain':'County remains the park source. City additions inside Ragged are excluded; the held Maintenance Road stays unchanged.',
 'heyward-community-forest':'City supplies the park geometry. The corrected saddle connector joins the three northern endpoints you marked; the old leg descending toward Round Top is removed. The route northeast of your third point stays unchanged.',
 'mcintire-park':'Keep both City and the full Rivanna network. Include the two reviewed City park additions.',
 'quarry-park':'Keep the entire Rivanna network and existing City trails. Add Quarry Old Road (city:3710); hold the other Quarry additions.'};
function selectPark(){const p=data.parks.find(p=>p.id===$('park').value);$('decision').textContent=descriptions[p.id];$('connectors').replaceChildren(...[...(data.manifest.retained_features||[]),...(data.manifest.connector_replacements||[])].filter(f=>f.park===p.id).map(f=>{const button=document.createElement('button');button.textContent=`Show ${f.label}`;button.onclick=()=>{if(ready)map.fitBounds(f.preview_bounds,{padding:65,duration:0});$('feature').textContent=f.review_note||f.reason;};return button;}));if(ready){map.fitBounds([[p.bounds[0],p.bounds[1]],[p.bounds[2],p.bounds[3]]],{padding:60,duration:0});map.getSource('boundary').setData({type:'Feature',properties:{},geometry:p.boundary});}}
function updateView(){if(!ready)return;for(const d of data.datasets)map.getSource(`preview-${d.dataset}`).setData(d[$('view').value]);}
async function init(){
 setupPointPicker();
 const response=await fetch('review.json');if(!response.ok)throw Error('Could not load prepared preview');data=await response.json();
 if(data.publication?.status==='published'){$('publication-status').textContent='Published to Mapbox';$('view').options[0].textContent='Published consolidation';}
 $('park').replaceChildren(...data.parks.map(p=>new Option(p.name,p.id)));const requested=new URLSearchParams(location.search).get('park');$('park').value=data.parks.some(p=>p.id===requested)?requested:'quarry-park';$('park').onchange=selectPark;$('view').onchange=updateView;
 $('boundaries').onchange=()=>{if(ready)map.setLayoutProperty('boundary-line','visibility',$('boundaries').checked?'visible':'none');};
 $('changes').replaceChildren(...data.datasets.map(d=>{const p=document.createElement('p');p.textContent=`${d.target}: ${d.changes.added} added, ${d.changes.changed} changed, ${d.changes.deleted} removed from display${d.publication_method==='retire-style-layers-keep-dataset'?' (dataset archived)':''}`;return p;}));
 selectPark();mapboxgl.accessToken=data.public_token;map=new mapboxgl.Map({container:'map',style:data.style,center:[-78.48,38.03],zoom:12});map.addControl(new mapboxgl.NavigationControl());
 map.on('load',()=>{
  const original=map.getStyle().layers;
  for(const d of data.datasets){
   const source=`preview-${d.dataset}`;map.addSource(source,{type:'geojson',data:d[$('view').value]});
   for(const layer of original.filter(l=>l['source-layer']===d.source_layer)){
    const clone=structuredClone(layer);clone.id=`preview-${layer.id}`;clone.source=source;delete clone['source-layer'];
    // The saved "before" dataset must remain inspectable after its live layers
    // are retired. The empty "after" source hides those tracks in the new view.
    if(data.manifest.style_proposal?.hide_layers.includes(layer.id))clone.layout={...clone.layout,visibility:'visible'};
    map.addLayer(clone,layer.id);map.setLayoutProperty(layer.id,'visibility','none');
   }
  }
  map.addSource('boundary',{type:'geojson',data:{type:'FeatureCollection',features:[]}});map.addLayer({id:'boundary-line',type:'line',source:'boundary',layout:{visibility:'none'},paint:{'line-color':'#d68627','line-width':2,'line-dasharray':[3,3]}});
  ready=true;selectPark();renderPoints();map.getCanvas().style.cursor=$('pick-points').checked?'crosshair':'';
 });
 map.on('click',event=>{if($('pick-points').checked){const p=event.lngLat.wrap();pickedPoints.push({lat:p.lat,lng:p.lng});savePoints();$('points-status').textContent=`Point ${pickedPoints.length} added. Drag a numbered pin to adjust it.`;return;}const hits=map.queryRenderedFeatures([[event.point.x-6,event.point.y-6],[event.point.x+6,event.point.y+6]]).filter(f=>f.layer.type==='line'&&(f.layer.id.startsWith('preview-')||f.sourceLayer==='Rivanna_Trail'));if(hits[0]){const f=hits[0];$('feature').textContent=`${f.sourceLayer==='Rivanna_Trail'?'Rivanna Trail':f.layer.id.replace('preview-','')} · ${f.properties.name||f.properties.NAME||f.properties.Name||f.properties.TrailName||'Unnamed trail'}${f.id?` · ${f.id}`:''}`;}});
}
init().catch(error=>{$('status').textContent=error.message;});
