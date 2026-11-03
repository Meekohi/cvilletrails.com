// Serve .trail-state/review-parks on port 8002 before running this check.
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8002/',{waitUntil:'networkidle'});
 await page.waitForFunction(()=>typeof ready!=='undefined'&&ready&&map.getLayer('park-boundary'));
 assert.equal(await page.locator('#name').textContent(),'Ivy Creek Natural Area');
 assert.equal(await page.locator('#winner').inputValue(),'');
 await page.locator('#recommend').click();
 assert.equal(await page.locator('#winner').inputValue(),'cjcm3ne8w0os033rw0ceoi0ye');
 await page.locator('#notes').fill('Test decision, not a real source approval.');
 const downloaded=page.waitForEvent('download');await page.locator('#export').click();
 await mkdir('test-results',{recursive:true});await(await downloaded).saveAs('test-results/park-decisions-test.json');
 const saved=JSON.parse(await readFile('test-results/park-decisions-test.json','utf8'));
 assert.equal(saved.decisions['ivy-creek-natural-area'].dataset,'cjcm3ne8w0os033rw0ceoi0ye');
 assert.equal(saved.decisions['ivy-creek-natural-area'].decision,'choose');
 await page.reload({waitUntil:'networkidle'});assert.equal(await page.locator('#notes').inputValue(),'Test decision, not a real source approval.');
 await page.waitForFunction(()=>typeof ready!=='undefined'&&ready&&map.getLayer('park-boundary'));
 await page.getByRole('checkbox',{name:'Show Albemarle County Trails',exact:true}).uncheck();
 assert.equal(await page.evaluate(()=>map.getLayoutProperty('compare-cjcm3ne8w0os033rw0ceoi0ye','visibility')),'none');
 await page.getByRole('checkbox',{name:'Show Albemarle County Trails',exact:true}).check();
 await page.screenshot({path:'test-results/park-review-ivy.png'});
 await page.getByRole('button',{name:/^Heyward Community Forest/}).click();
 await page.getByRole('button',{name:/^Ragged Mountain/}).click();
 assert.equal(await page.locator('#name').textContent(),'Ragged Mountain');
 assert.ok((await page.locator('#cautions').textContent()).includes('Maintenance Road'));
 await page.locator('#discuss').click();assert.equal(await page.locator('#winner').inputValue(),'discuss');
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.equal((await page.request.get('http://127.0.0.1:8002/.env.local')).status(),404);
 assert.deepEqual(errors,[]);
 console.log('Park review passed: overlays, dataset toggles, source choices, export, persistence, rapid park switching, mobile layout, secret exclusion.');
}finally{await browser.close();}
