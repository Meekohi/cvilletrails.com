import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1450,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8008/',{waitUntil:'networkidle'});await page.waitForFunction(()=>window.__reviewMap?.loaded()&&window.__reviewMap.getLayer('review-trails'));
 assert.equal(await page.locator('#parks option').count(),44);assert.match(await page.locator('#summary').textContent(),/14 eligible.*3 held/);
 const ids=await page.evaluate(()=>[...new Set(window.__reviewMap.queryRenderedFeatures({layers:['review-trails']}).map(f=>f.properties.GlobalID))]);assert.equal(ids.length,14);
 await page.screenshot({path:'test-results/lake-anna-gis-preview.png'});
 await page.locator('#held').uncheck();assert.equal(await page.evaluate(()=>window.__reviewMap.getLayoutProperty('review-held','visibility')),'none');
 await page.locator('#parks').selectOption({label:'Bear Creek Lake State Park'});await page.waitForFunction(()=>window.__reviewMap.loaded());
 await page.locator('#notes').fill('Browser test: inspect official map and alerts before import.');await page.locator('#include').click();
 const pending=page.waitForEvent('download');await page.locator('#export').click();const download=await pending;const value=JSON.parse(await readFile(await download.path(),'utf8'));
 assert.equal(value.kind,'virginia-state-parks-review');assert.equal(value.decisions['Bear Creek Lake State Park'].decision,'queue-import');assert.equal(value.review_hash,await page.evaluate(()=>window.__reviewReport.review_hash));
 await page.reload({waitUntil:'networkidle'});await page.waitForFunction(()=>window.__reviewMap?.loaded()&&window.__reviewMap.getLayer('review-trails'));await page.locator('#parks').selectOption({label:'Bear Creek Lake State Park'});assert.match(await page.locator('#state').textContent(),/queue-import/);assert.match(await page.locator('#notes').inputValue(),/Browser test/);assert.deepEqual(errors,[]);
 console.log('Statewide park selector, 14 Lake Anna trails / 3 held records, visibility, notes, export and persistence passed.');
}finally{await browser.close();}
