// Serve .trail-state/review-consolidation on port 8003.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8003/',{waitUntil:'networkidle'});
 await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
 await page.evaluate(()=>map.on('error',e=>{window.mapErrors=(window.mapErrors||[]).concat(e.error.message);}));
 assert.equal(await page.locator('#park').inputValue(),'quarry-park');
 assert.match(await page.locator('#decision').textContent(),/Old Road/);
 const inspect=()=>page.evaluate(()=>{
  const layers=map.getStyle().layers,city=data.datasets.find(d=>d.target==='city');
  const rivanna=layers.filter(l=>l.type==='line'&&l['source-layer']==='Rivanna_Trail');
  const preview=layers.filter(l=>l.type==='line'&&l.id.startsWith('preview-'));
  return {oldRoad:map.getSource(`preview-${city.dataset}`).serialize().data.features.some(f=>f.id==='city:3710'),
   rivannaOnTop:Math.min(...rivanna.map(l=>layers.indexOf(l)))>Math.max(...preview.map(l=>layers.indexOf(l))),
   protectedNotReplaced:!map.getSource('preview-cjawyutol0r7d2wo1z7eb0wiy')};
 });
 assert.deepEqual(await inspect(),{oldRoad:true,rivannaOnTop:true,protectedNotReplaced:true});
 await page.locator('#view').selectOption('before');
 assert.equal((await inspect()).oldRoad,false);
 await page.locator('#view').selectOption('after');
 await page.waitForFunction(()=>map.loaded());
 await mkdir('test-results',{recursive:true});
 await page.screenshot({path:'test-results/consolidation-quarry.png'});
 for(const park of ['heyward-community-forest','ragged-mountain','ivy-creek-natural-area','mcintire-park']){
  await page.locator('#park').selectOption(park);
  await page.waitForFunction(()=>map.loaded());
 }
 await page.locator('#park').selectOption('heyward-community-forest');
 await page.getByRole('button',{name:'Show Round Top saddle connector'}).click();
 assert.match(await page.locator('#feature').textContent(),/Corrected northern connector/);
 assert.equal(await page.evaluate(()=>{
  const d=data.datasets.find(d=>d.target==='strava'),id='8d36129f3e99bffe6d1807c85f373009';
  const old=d.before.features.find(f=>f.id===id).geometry.coordinates;
  const corrected=d.after.features.find(f=>f.id===id).geometry.coordinates;
  const city=data.datasets.find(d=>d.target==='city').after.features;
  const west=city.find(f=>f.id==='city:3266').geometry.coordinates.at(-1);
  const middle=city.find(f=>f.id==='city:3271').geometry.coordinates[0];
  return JSON.stringify(corrected[0])===JSON.stringify(west)&&JSON.stringify(corrected[1])===JSON.stringify(middle)&&
   JSON.stringify(corrected.slice(2))===JSON.stringify(old.slice(5))&&!corrected.some(p=>JSON.stringify(p)===JSON.stringify(old[0]));
 }),true);
 await page.locator('#boundaries').check();
 await page.waitForFunction(()=>map.loaded());
 await page.screenshot({path:'test-results/consolidation-heyward.png'});
 assert.equal(await page.evaluate(()=>map.getLayoutProperty('boundary-line','visibility')),'visible');
 await page.locator('#pick-points').check();
 const clickPosition=await page.evaluate(()=>{const p=map.project([-78.552447,38.032547]),rect=map.getCanvas().getBoundingClientRect();return {x:p.x+rect.left,y:p.y+rect.top};});
 await page.mouse.click(clickPosition.x,clickPosition.y);
 const pickedText=await page.locator('#coordinates').inputValue();
 const coordinates=pickedText.match(/^1\. lat: ([-\d.]+), lng: ([-\d.]+)$/);
 assert.ok(coordinates);
 // A screen click is quantized to pixels; allow roughly one metre here.
 assert.ok(Math.abs(Number(coordinates[1])-38.032547)<.00001);
 assert.ok(Math.abs(Number(coordinates[2])+78.552447)<.00001);
 assert.equal(await page.locator('.coordinate-pin').count(),1);
 // Turning picking off restores normal trail inspection without adding points.
 await page.locator('#pick-points').uncheck();
 await page.mouse.click(clickPosition.x,clickPosition.y);
 assert.equal(await page.locator('.coordinate-pin').count(),1);
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);
 await page.locator('#copy-points').click();
 assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),pickedText);
 await page.reload({waitUntil:'networkidle'});
 await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
 assert.equal(await page.locator('#coordinates').inputValue(),pickedText);
 assert.equal(await page.locator('.coordinate-pin').count(),1);
 await page.locator('#undo-point').click();
 assert.equal(await page.locator('#coordinates').inputValue(),'');
 assert.equal(await page.locator('.coordinate-pin').count(),0);
 assert.equal(await page.locator('#copy-points').isDisabled(),true);
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.equal((await page.request.get('http://127.0.0.1:8003/.env.local')).status(),404);
 assert.deepEqual(await page.evaluate(()=>window.mapErrors||[]),[]);
 assert.deepEqual(errors,[]);
 console.log('Consolidation preview passed: geometry, Rivanna, parks, coordinate picking, clipboard, persistence, undo, mobile layout, secret exclusion.');
} finally {await browser.close();}
