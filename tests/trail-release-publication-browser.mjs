// Run after publication against the deployed site; --fresh changes only tile cache keys.
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
const fresh=process.argv.includes('--fresh');
const root='.trail-state/tnc-usfs-publish';
const plan=JSON.parse(await readFile(`${root}/supplemental-plan.json`,'utf8'));
const at=JSON.parse(await readFile(`${root}/at-plan.json`,'utf8'));
const proposal=JSON.parse(await readFile(`${root}/style-proposed.json`,'utf8'));
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
  const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[];
  page.on('pageerror',(e)=>errors.push(e.message));
  await page.route('**/assets/app.js',async(route)=>{
    const response=await route.fetch();let body=(await response.text()).replace('map = new mapboxgl.Map({','map = window.__testMap = new mapboxgl.Map({');
    if(fresh)body=body.replace('map = window.__testMap = new mapboxgl.Map({',`map = window.__testMap = new mapboxgl.Map({transformRequest:(url,type)=>({url:type==='Tile'&&url.includes('/v4/')?url+(url.includes('?')?'&':'?')+'fresh=trail-release-${plan.approval_hash.slice(0,12)}':url}),`);
    await route.fulfill({response,body});
  });
  await page.goto(process.env.PUBLIC_SITE_URL||'https://cvilletrails.com/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__testMap?.isStyleLoaded());
  const style=await page.evaluate(()=>window.__testMap.getStyle());
  assert.equal(style.sources.composite.url,proposal.sources.composite.url);
  for(const id of ['strava-trail','shenandoah-np fringe','shenandoah-np-trail']){
    const actual=style.layers.find(l=>l.id===id),expected=proposal.layers.find(l=>l.id===id);
    assert.deepEqual(actual.paint,expected.paint);assert.deepEqual(actual.filter,expected.filter);
  }
  const targets=[
    ['Bear Loop',plan.after.features.find(f=>f.properties.source_id==='bear-loop'),'strava-trail'],
    ['Tuscarora',plan.after.features.find(f=>f.properties.name==='TUSCARORA - BEAR WALLOW'),'strava-trail'],
    ['Cascades connector',plan.after.features.find(f=>f.properties.name==='CASCADES NORTH CONNECTOR'),'strava-trail'],
    ['Retained PATC',plan.after.features.find(f=>f.properties.pipeline_id==='legacy-patc'),'strava-trail'],
    ['AT',at.after.features.find(f=>f.geometry.type==='LineString'&&f.geometry.coordinates.length>30),'appalachian-trail']
  ];
  const results=[];
  for(const [name,feature,layer] of targets){
    assert.ok(feature,`Missing probe ${name}`);
    const coords=feature.geometry.type==='LineString'?feature.geometry.coordinates:feature.geometry.coordinates.flat();
    const center=coords[Math.floor(coords.length/2)];
    for(const zoom of [10,12,14,16]){
      await page.evaluate(({center,zoom})=>window.__testMap.jumpTo({center,zoom}),{center,zoom});
      await page.waitForFunction(()=>window.__testMap.loaded()&&!window.__testMap.isMoving(),null,{timeout:60000});
      const result=await page.evaluate(({feature,layer})=>{
        const matches=window.__testMap.queryRenderedFeatures({layers:[layer]}).filter(f=>f.properties.source_feature_id===feature.properties.source_feature_id&&f.properties.source_id===feature.properties.source_id&&f.properties.name===feature.properties.name&&f.properties.pipeline_id===feature.properties.pipeline_id);
        return {rendered:matches.length,colors:matches.map(f=>f.layer.paint['line-color'])};
      },{feature,layer});
      results.push({name,zoom,...result});
      if(name==='Tuscarora'||name==='Retained PATC'){
        const duplicate=await page.evaluate(()=>window.__testMap.queryRenderedFeatures({layers:['shenandoah-np-trail']}).some(f=>f.properties.Loc_Name==='Tuscarora Trail (outside park boundary)'&&f.properties.GPSDate==='12/21/2019'));
        assert.equal(duplicate,false,'Retired PATC route still renders over its replacement');
      }
      if(zoom===14){await mkdir('test-results',{recursive:true});await page.screenshot({path:`test-results/published-${name.replaceAll(' ','-')}-${fresh?'fresh':'standard'}.png`});}
    }
  }
  // The preserved park and RT layers must still render in the actual public map.
  for(const [name,center,layer] of [['DCR',[-79.8,37.9],'strava-trail'],['Rivanna',[-78.523,38.026],'rivanna-trail']]){
    await page.evaluate(center=>window.__testMap.jumpTo({center,zoom:14}),center);
    await page.waitForFunction(()=>window.__testMap.loaded(),null,{timeout:60000});
    results.push({name,zoom:14,rendered:await page.evaluate(layer=>window.__testMap.queryRenderedFeatures({layers:[layer]}).length,layer)});
  }
  const report={checked_at:new Date().toISOString(),mode:fresh?'fresh-tile-key-only':'ordinary-public-style-and-tiles',results,page_errors:errors};
  await writeFile(`${root}/render-${fresh?'fresh':'standard'}.json`,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
  assert.ok(results.every(r=>r.rendered>0),'Some published features are absent at a tested zoom');assert.deepEqual(errors,[]);
}finally{await browser.close();}
