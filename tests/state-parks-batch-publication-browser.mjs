// Validate actual remote tiles in every accepted park; never substitute local geometry.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
const fresh=process.argv.includes('--fresh');
const accepted=JSON.parse(await readFile('pipelines/virginia-state-parks/data/statewide-2026-11-03.geojson','utf8'));
const systems=JSON.parse(await readFile('data/systems.json','utf8'));
const groups=new Map();for(const f of accepted.features){const id=f.properties.system_id;if(!groups.has(id))groups.set(id,[]);groups.get(id).push(f)}
const sample=process.argv.includes('--sample');
if(sample)for(const id of [...groups.keys()].slice(3))groups.delete(id);
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const report={checked_at:new Date().toISOString(),mode:fresh?'diagnostic-fresh-tiles':'ordinary-public-tiles',sample,parks:[],page_errors:[]};
const queue=[...groups.entries()];
try {
 async function worker(){
  const page=await browser.newPage({viewport:{width:1400,height:1100}});
  page.on('pageerror',e=>report.page_errors.push(e.message));
  await page.route('**/assets/app.js',async route=>{
   const response=await route.fetch();let body=(await response.text()).replace('map = new mapboxgl.Map({','map = window.__testMap = new mapboxgl.Map({');
   if(fresh)body=body.replace('map = window.__testMap = new mapboxgl.Map({',`map = window.__testMap = new mapboxgl.Map({transformRequest:(url,type)=>({url:type==='Tile'&&url.includes('/v4/')?url+(url.includes('?')?'&':'?')+'fresh=statewide-${Date.now()}':url}),`);
   await route.fulfill({response,body});
  });
  await page.goto(process.env.TEST_SITE_URL||'http://127.0.0.1:8000/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__testMap?.loaded());
  while(queue.length){
   const [sid,features]=queue.shift();
   const points=features.flatMap(f=>f.geometry.type==='LineString'?f.geometry.coordinates:f.geometry.coordinates.flat());
   const bounds=[Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))];
   await page.evaluate(b=>window.__testMap.fitBounds(b,{padding:90,maxZoom:13,duration:0}),bounds);
   await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
   const rendered=await page.evaluate(sid=>({zoom:window.__testMap.getZoom(),ids:[...new Set(window.__testMap.queryRenderedFeatures({layers:['strava-trail']}).filter(f=>f.properties.system_id===sid).map(f=>f.properties.source_feature_id))].sort()}),sid);
   const expected=features.map(f=>f.properties.source_feature_id).sort();
   const first=features[0],coords=first.geometry.type==='LineString'?first.geometry.coordinates:first.geometry.coordinates.flat(),center=coords[Math.floor(coords.length/2)];
   await page.evaluate(center=>window.__testMap.jumpTo({center,zoom:16}),center);
   await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
   const detail=await page.evaluate(fid=>window.__testMap.queryRenderedFeatures({layers:['strava-trail']}).find(f=>f.properties.source_feature_id===fid)?.properties,first.properties.source_feature_id);
   const paint=await page.evaluate(()=>window.__testMap.getPaintProperty('strava-trail','line-color'));
   const row={system_id:sid,name:systems.find(s=>s.id===sid)?.name,expected_count:expected.length,overview:rendered,missing:expected.filter(id=>!rendered.ids.includes(id)),
    detail:{zoom:16,feature_id:first.id,present:!!detail,color_matches:detail?.display_color===first.properties.display_color},
    style_matches:JSON.stringify(paint?.slice(0,3))===JSON.stringify(['case',['==',['get','pipeline_id'],'virginia-state-parks'],['coalesce',['get','display_color'],'#ded0c5']])};
   row.passed=row.missing.length===0&&row.detail.present&&row.detail.color_matches&&row.style_matches;report.parks.push(row);
   if(sid==='dcr-bear-creek-lake-state-park')await page.screenshot({path:`test-results/statewide-published-${fresh?'fresh':'ordinary'}.png`});
   console.log(`${row.passed?'PASS':'PENDING'} ${row.name}: ${rendered.ids.length}/${expected.length} overview; detail ${row.detail.present}`);
  }
  await page.close();
 }
 await Promise.all([worker(),worker(),worker()]);
 report.parks.sort((a,b)=>a.system_id.localeCompare(b.system_id));
 report.passed=report.parks.length===groups.size&&report.parks.every(p=>p.passed)&&!report.page_errors.length;
 await writeFile(`test-results/statewide-publication-${fresh?'fresh':'ordinary'}${sample?'-sample':''}.json`,JSON.stringify(report,null,2)+'\n');
 assert.ok(report.passed,'Some ordinary style/tiles may still be cached; compare --fresh and inspect the saved report.');
 console.log(`Verified ${[...groups.values()].reduce((n,fs)=>n+fs.length,0)} trail IDs across ${groups.size} park overview views and ${groups.size} zoom-16 detail views.`);
} finally {await browser.close()}
