// Serve the built site on 8000, or use TEST_SITE_URL for the published site.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const systems=JSON.parse(await readFile('data/systems.json','utf8'));
const originalAudit=JSON.parse(await readFile('pipelines/visitor-info/reviews/2026-11-03-catalog.json','utf8'));
const audit=process.argv[2]?JSON.parse(await readFile(process.argv[2],'utf8')):originalAudit;
const centers={...originalAudit.preview_centers,...audit.preview_centers};
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await browser.newPage({viewport:{width:1200,height:900}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/assets/app.js',async route=>{
    const response=await route.fetch();
    await route.fulfill({response,body:(await response.text()).replace('map = new mapboxgl.Map','map = window.__testMap = new mapboxgl.Map')});
  });
  await page.goto(process.env.TEST_SITE_URL||'http://127.0.0.1:8000/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__testMap?.loaded());
  for(const id of audit.added_systems){
    const system=systems.find(s=>s.id===id);
    if(audit.preview_fit_bounds){
      await page.evaluate(bounds=>window.__testMap.fitBounds(bounds,{padding:80,maxZoom:15,duration:0}),system.bounds);
    }else{
      await page.evaluate(view=>window.__testMap.jumpTo(view),{center:centers[id],zoom:audit.preview_zoom||17});
    }
    await page.waitForFunction(name=>document.querySelector('#map-title-text').textContent===name,system.context_title||system.name);
    if(!await page.locator('#panel').isVisible())await page.locator('#map-title').click();
    assert.equal(await page.locator('#panel-title').textContent(),system.name);
    assert.equal(await page.locator('.visitor-info dt').count(),system.visitor_info.length);
    assert.equal(await page.locator('.info-sources a').count(),system.info_sources.length);
    for(const fact of system.visitor_info)assert.ok((await page.locator('.visitor-info').textContent()).includes(fact.value));
    assert.equal(await page.locator('.info-sources a').first().getAttribute('href'),system.url);
    if(system.map_note)assert.equal(await page.locator('.map-note').textContent(),system.map_note);
    console.log('Verified infobox:',id);
  }
  await page.setViewportSize({width:390,height:844});
  const mobileId=audit.mobile_system||audit.added_systems[0],mobileSystem=systems.find(s=>s.id===mobileId);
  await page.evaluate(center=>window.__testMap.jumpTo({center,zoom:17}),centers[mobileId]);
  await page.waitForFunction(name=>document.querySelector('#map-title-text').textContent===name,mobileSystem.context_title||mobileSystem.name);
  assert.equal(await page.locator('#panel-title').textContent(),mobileSystem.name);
  for(const fact of mobileSystem.visitor_info)assert.ok((await page.locator('.visitor-info').textContent()).includes(fact.value));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.brand-copy')).opacity==='1'&&getComputedStyle(document.querySelector('#panel-content')).opacity==='1');
  await page.screenshot({path:`test-results/${mobileId}-info-mobile.png`});
  // A shared-source trail tap inside McIntire must show McIntire's facts.
  await page.setViewportSize({width:1200,height:900});
  await page.evaluate(center=>window.__testMap.jumpTo({center,zoom:17}),centers['mcintire-park']);
  await page.waitForFunction(()=>window.__testMap.loaded()&&document.querySelector('#map-title-text').textContent==='McIntire Park');
  await page.locator('#close-panel').click();
  const point=await page.evaluate(async()=>{
    const {systemForFeature}=await import('/assets/data.js');
    const systems=await(await fetch('/data/systems.json')).json();
    const map=window.__testMap;
    for(const f of map.queryRenderedFeatures().filter(f=>f.sourceLayer==='City_Trails_2021-10-13')){
      const lines=f.geometry.type==='LineString'?[f.geometry.coordinates]:f.geometry.coordinates;
      for(const line of lines)for(const c of line){
        const p=map.project(c);
        if(p.x>400&&p.x<1100&&p.y>100&&p.y<750&&systemForFeature(systems,f,c)?.id==='mcintire-park')return {x:p.x,y:p.y};
      }
    }
  });
  assert.ok(point,'a visible City trail lies inside McIntire');
  await page.mouse.click(point.x,point.y);
  await page.locator('#panel').waitFor({state:'visible'});
  assert.match(await page.locator('.visitor-info').textContent(),/10 p.m./);
  assert.match(await page.locator('.info-sources a').first().getAttribute('href'),/McIntire-Park/);
  assert.deepEqual(errors,[]);
  console.log(`All ${audit.added_systems.length} contexts, official links, visitor facts, shared-layer tap and mobile layout passed.`);
}finally{await browser.close();}
