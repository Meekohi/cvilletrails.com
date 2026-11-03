// Optional post-publication check against remote Mapbox data (serve dist on 8000).
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
const fresh=process.argv.includes('--fresh');
const plan=JSON.parse(await readFile('.trail-state/plans/rivanna-reviewed.json','utf8'));
const proposal=JSON.parse(await readFile('.trail-state/review-rivanna-candidate/style-proposal.json','utf8'));
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await browser.newPage({viewport:{width:1400,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/assets/app.js',async route=>{
    const response=await route.fetch();
    let body=(await response.text()).replace('map = new mapboxgl.Map({','map = window.__testMap = new mapboxgl.Map({');
    if(fresh){
      body=body.replace('map = window.__testMap = new mapboxgl.Map({',`map = window.__testMap = new mapboxgl.Map({ transformRequest: (url,type) => ({url:type==='Tile'&&url.includes('/v4/')?url+(url.includes('?')?'&':'?')+'fresh=rivanna-${plan.approval_hash.slice(0,12)}':url}),`);
      body=body.replace("style: 'mapbox://styles/meekohi/ckkolybrr6tjx17mjqflqw16b'", "style: 'https://api.mapbox.com/styles/v1/meekohi/ckkolybrr6tjx17mjqflqw16b?optimize=false&access_token='+mapboxgl.accessToken");
    }
    await route.fulfill({response,body});
  });
  await page.goto('http://127.0.0.1:8000/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__testMap?.isStyleLoaded());
  const styles=await page.evaluate(()=>Object.fromEntries(window.__testMap.getStyle().layers.filter(l=>l['source-layer']==='Rivanna_Trail').map(l=>[l.id,l])));
  const expected=Object.fromEntries(proposal.layers.filter(l=>l['source-layer']==='Rivanna_Trail').map(l=>[l.id,l]));
  let styleMatches=true;
  try {for(const id of Object.keys(expected)){assert.deepEqual(styles[id]?.paint,expected[id].paint);assert.deepEqual(styles[id]?.layout,expected[id].layout);}}
  catch {styleMatches=false;}
  const report={checked_at:new Date().toISOString(),mode:fresh?'fresh-v4-tiles-and-unoptimized-style':'standard-public-style-and-tiles',style_matches_proposal:styleMatches,results:[]};
  if(styleMatches){
    const targets=plan.after.features.filter(f=>plan.changes.added.includes(f.id)||f.id==='979e29e234bf508b2d9b8f6808757de0'||f.id==='8801a8379c2f586c2213fa33dd8963dd');
    await page.evaluate(features=>{
      const bounds=new mapboxgl.LngLatBounds();
      for(const f of features)for(const c of f.geometry.type==='LineString'?f.geometry.coordinates:f.geometry.coordinates.flat())bounds.extend(c);
      window.__testMap.fitBounds(bounds,{padding:70,duration:0});
    },targets);
    await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
    report.results=await page.evaluate(features=>features.map(f=>{
      const matches=window.__testMap.queryRenderedFeatures({layers:['rivanna-trail']}).filter(r=>r.properties.section===f.properties.section);
      return {feature_id:f.id,section:f.properties.section,rendered_segments:matches.length,
              status_matches:matches.length>0&&matches.every(r=>r.properties.access_status===f.properties.access_status)};
    }),targets);
    await page.evaluate(()=>window.__testMap.jumpTo({center:[-78.524,38.0245],zoom:14.6}));
    await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving());
    await page.screenshot({path:`test-results/rivanna-published-${fresh?'fresh':'standard'}.png`});
  }
  report.page_errors=errors;
  await writeFile(`.trail-state/mapbox/rivanna-render-${fresh?'fresh':'standard'}.json`,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
  assert.ok(styleMatches,'Published style has not reached this cache key');
  assert.ok(report.results.length===9&&report.results.every(r=>r.rendered_segments>0&&r.status_matches),'Some reviewed routes or closure status are absent from these tiles');
  assert.deepEqual(errors,[]);
}finally{await browser.close();}
