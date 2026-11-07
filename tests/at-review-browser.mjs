import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
  const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];
  page.on('pageerror',(e)=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8011/at/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.atReviewReady);
  await page.waitForFunction(()=>window.atMaps.every((m)=>m.loaded()&&m.queryRenderedFeatures({layers:['at-centerline']}).length>0),null,{timeout:60000});
  assert.equal(await page.locator('#segment option').count(),16);
  assert.match(await page.locator('#summary').textContent(),/627 old segments → 791 official segments/);
  assert.deepEqual(await page.evaluate(()=>window.atMaps.map((m)=>m.getLayer('appalachian-trail'))),[undefined,undefined]);
  await mkdir('test-results',{recursive:true});
  await page.screenshot({path:'test-results/at-source-comparison.png'});
  await page.locator('#overlay').uncheck();
  assert.equal(await page.evaluate(()=>window.atMaps[1].getLayoutProperty('old-overlay','visibility')),'none');
  await page.locator('#segment').selectOption('');
  assert.match(await page.locator('#detail').textContent(),/not proven new trail mileage/);
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:'test-results/at-source-comparison-mobile.png'});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:'rendered before/after geometry, bounded comparison, overlay toggle, existing AT layer removed, mobile'}));
}finally{await browser.close();}
