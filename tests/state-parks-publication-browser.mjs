// Actual remote tiles only. Serve dist on 8000 or set TEST_SITE_URL.
// --fresh diagnoses tile/style propagation separately from ordinary requests.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
const fresh=process.argv.includes('--fresh');
const trails=JSON.parse(await readFile('pipelines/virginia-state-parks/data/lake-anna.geojson','utf8'));
const points=trails.features.flatMap(f=>f.geometry.type==='LineString'?f.geometry.coordinates:f.geometry.coordinates.flat());
const bounds=[Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))];
const center=[(bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2];
const expected=trails.features.map(f=>f.properties.source_feature_id).sort();
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const report={checked_at:new Date().toISOString(),mode:fresh?'diagnostic-fresh-tiles-unoptimized-style':'ordinary-public-style-and-tiles',zooms:[],junctions:[]};
try{
  const page=await browser.newPage({viewport:{width:1400,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/assets/app.js',async route=>{
    const response=await route.fetch();let body=(await response.text()).replace('map = new mapboxgl.Map({','map = window.__testMap = new mapboxgl.Map({');
    if(fresh){
      body=body.replace('map = window.__testMap = new mapboxgl.Map({',`map = window.__testMap = new mapboxgl.Map({transformRequest:(url,type)=>({url:type==='Tile'&&url.includes('/v4/')?url+(url.includes('?')?'&':'?')+'fresh=state-parks-${Date.now()}':url}),`);
      body=body.replace("style: 'mapbox://styles/meekohi/ckkolybrr6tjx17mjqflqw16b'","style: 'https://api.mapbox.com/styles/v1/meekohi/ckkolybrr6tjx17mjqflqw16b?optimize=false&access_token='+mapboxgl.accessToken");
    }
    await route.fulfill({response,body});
  });
  await page.goto((process.env.TEST_SITE_URL||'http://127.0.0.1:8000/')+`#13/${center[1]}/${center[0]}`,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__testMap?.loaded());
  report.line_color=await page.evaluate(()=>window.__testMap.getPaintProperty('strava-trail','line-color'));
  report.style_matches=JSON.stringify(report.line_color?.slice(0,3))===JSON.stringify(['case',['==',['get','pipeline_id'],'virginia-state-parks'],['coalesce',['get','display_color'],'#ded0c5']]);
  for(const zoom of [10,12,13]){
    await page.evaluate(view=>window.__testMap.jumpTo(view),{center,zoom});
    await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
    const ids=await page.evaluate(()=>[...new Set(window.__testMap.queryRenderedFeatures({layers:['strava-trail']}).filter(f=>f.properties.system_id==='lake-anna').map(f=>f.properties.source_feature_id))].sort());
    report.zooms.push({zoom,feature_ids:ids,all_present:JSON.stringify(ids)===JSON.stringify(expected)});
  }
  await page.screenshot({path:`test-results/lake-anna-published-${fresh?'fresh':'ordinary'}.png`});
  for(const f of trails.features){
    const coords=f.geometry.type==='LineString'?f.geometry.coordinates:f.geometry.coordinates.flat();
    await page.evaluate(center=>window.__testMap.jumpTo({center,zoom:16}),coords[Math.floor(coords.length/2)]);
    await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
    const found=await page.evaluate(fid=>window.__testMap.queryRenderedFeatures({layers:['strava-trail']}).some(r=>r.properties.system_id==='lake-anna'&&r.properties.source_feature_id===fid),f.properties.source_feature_id);
    report.junctions.push({feature_id:f.id,zoom:16,present:found});
  }
  report.page_errors=errors;
  report.passed=report.style_matches&&report.zooms.every(x=>x.all_present)&&report.junctions.every(x=>x.present)&&errors.length===0;
  await writeFile(`test-results/lake-anna-publication-${fresh?'fresh':'ordinary'}.json`,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({mode:report.mode,style_matches:report.style_matches,zooms:report.zooms.map(r=>({zoom:r.zoom,count:r.feature_ids.length,all_present:r.all_present})),detail_views:report.junctions.length,all_details_present:report.junctions.every(r=>r.present),passed:report.passed}));
  assert.ok(report.passed,'Public style or tiles not current at every sampled zoom; inspect report and compare diagnostic fresh mode.');
}finally{await browser.close();}
