// Actual remote tiles only. Serve dist on 8000 or set TEST_SITE_URL.
// --fresh diagnoses tile/style propagation separately from ordinary requests.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
const fresh=process.argv.includes('--fresh');
const trails=JSON.parse(await readFile('pipelines/fortunes-cove/data/trails.geojson','utf8'));
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
      body=body.replace('map = window.__testMap = new mapboxgl.Map({',`map = window.__testMap = new mapboxgl.Map({transformRequest:(url,type)=>({url:type==='Tile'&&url.includes('/v4/')?url+(url.includes('?')?'&':'?')+'fresh=fortunes-${Date.now()}':url}),`);
      body=body.replace("style: 'mapbox://styles/meekohi/ckkolybrr6tjx17mjqflqw16b'","style: 'https://api.mapbox.com/styles/v1/meekohi/ckkolybrr6tjx17mjqflqw16b?optimize=false&access_token='+mapboxgl.accessToken");
    }
    await route.fulfill({response,body});
  });
  await page.goto((process.env.TEST_SITE_URL||'http://127.0.0.1:8000/')+'#14/37.79042/-78.89382',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__testMap?.loaded());
  report.line_color=await page.evaluate(()=>window.__testMap.getPaintProperty('strava-trail','line-color'));
  report.style_matches=JSON.stringify(report.line_color?.slice(0,3))===JSON.stringify(['case',['==',['get','system_id'],'fortunes-cove'],['match',['get','color'],'yellow','#ffe14f','white','#ffffff','#ded0c5']]);
  for(const zoom of [10,12,14]){
    await page.evaluate(zoom=>window.__testMap.jumpTo({center:[-78.89382,37.79042],zoom}),zoom);
    await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
    const ids=await page.evaluate(()=>[...new Set(window.__testMap.queryRenderedFeatures({layers:['strava-trail']}).filter(f=>f.properties.system_id==='fortunes-cove').map(f=>f.properties.source_feature_id))].sort());
    report.zooms.push({zoom,feature_ids:ids,all_present:JSON.stringify(ids)===JSON.stringify(expected)});
  }
  await page.screenshot({path:`test-results/fortunes-cove-published-${fresh?'fresh':'ordinary'}.png`});
  for(const f of trails.features){
    const coords=f.geometry.coordinates;
    await page.evaluate(center=>window.__testMap.jumpTo({center,zoom:16}),coords[Math.floor(coords.length/2)]);
    await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
    const found=await page.evaluate(fid=>window.__testMap.queryRenderedFeatures({layers:['strava-trail']}).some(r=>r.properties.system_id==='fortunes-cove'&&r.properties.source_feature_id===fid),f.properties.source_feature_id);
    report.junctions.push({feature_id:f.id,zoom:16,present:found});
  }
  report.page_errors=errors;
  report.passed=report.style_matches&&report.zooms.every(x=>x.all_present)&&report.junctions.every(x=>x.present)&&errors.length===0;
  await writeFile(`test-results/fortunes-cove-publication-${fresh?'fresh':'ordinary'}.json`,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
  assert.ok(report.passed,'Public style or tiles not current at every sampled zoom; inspect report and compare diagnostic fresh mode.');
}finally{await browser.close();}
