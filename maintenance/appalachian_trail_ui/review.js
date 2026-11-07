const $=(id)=>document.getElementById(id);
const [report,before,after,preview]=await Promise.all(['comparison.json','before.geojson','candidate.geojson','preview.json'].map(async(url)=>{const response=await fetch(url);if(!response.ok)throw new Error(`Cannot load ${url}`);return response.json();}));
const attention=report.rows.filter((row)=>row.attention);
$('summary').textContent=`${report.before_count} old segments → ${report.after_count} official segments, clipped to existing map coverage. ${attention.length} old segments have substantial alignment differences; ${report.clipped_ids.length} official records are clipped at the coverage boundary.`;
for(const [i,row] of [null,...attention].entries()){
  const option=document.createElement('option');option.value=row?.id||'';
  option.textContent=row?`Difference ${i}: ${(row.length_m/1609.344).toFixed(2)} mi · ${Math.round(row.coverage['100']*100)}% within 100 m`:'Entire existing coverage';
  $('segment').append(option);
}
mapboxgl.accessToken=preview.public_token;
const maps=['before','after'].map((container)=>new mapboxgl.Map({container,style:'style.json',center:[-79.6,38],zoom:9}));
window.atMaps=maps;
let syncing=false;
for(const [i,map] of maps.entries()){
  map.addControl(new mapboxgl.NavigationControl());
  map.on('move',()=>{if(syncing)return;syncing=true;maps[1-i].jumpTo({center:map.getCenter(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch(),padding:map.getPadding()});syncing=false;});
}
await Promise.all(maps.map((map)=>new Promise((resolve)=>map.on('load',resolve))));
for(const [i,map] of maps.entries()){
  map.addSource('centerline',{type:'geojson',data:i?after:before});
  map.addLayer({id:'at-outline',type:'line',source:'centerline',paint:{'line-color':'#333','line-width':6}});
  map.addLayer({id:'at-centerline',type:'line',source:'centerline',paint:{'line-color':'white','line-width':3}});
}
maps[1].addSource('old',{type:'geojson',data:before});
maps[1].addLayer({id:'old-overlay',type:'line',source:'old',paint:{'line-color':'#e87b15','line-width':2,'line-dasharray':[2,2]}});
$('overlay').onchange=()=>maps[1].setLayoutProperty('old-overlay','visibility',$('overlay').checked?'visible':'none');
function fit(){
  const row=attention.find((r)=>r.id===$('segment').value),bounds=row?.bounds||report.scope.bounds;
  maps[0].fitBounds([bounds.slice(0,2),bounds.slice(2)],{padding:40,maxZoom:16,duration:0,retainPadding:false});
  $('detail').textContent=row?`Old segment ${row.id}: ${Math.round(row.coverage['20']*100)}% within 20 m of the official centerline. Inspect both maps for changes in alignment.`:`Old geometry: ${report.before_miles.toFixed(1)} mi; official geometry: ${report.after_miles.toFixed(1)} mi. This measures source geometry, not proven new trail mileage.`;
}
$('segment').onchange=fit;
if(attention.length)$('segment').value=attention[0].id;
fit();window.atReviewReady=true;
