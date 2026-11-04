// Build/serve dist on port 8000, or set TEST_SITE_URL to verify a deployment.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await browser.newPage({viewport:{width:1200,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/assets/app.js',async route=>{
    const response=await route.fetch();
    await route.fulfill({response,body:(await response.text()).replace('map = new mapboxgl.Map','map = window.__testMap = new mapboxgl.Map')});
  });
  await page.goto(process.env.TEST_SITE_URL||'http://127.0.0.1:8000/',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.__testMap?.loaded());
  const ragged={center:[-78.578,38.026],zoom:15};
  const monticello={center:[-78.465,38.004],zoom:15};
  const overview={center:[-78.482,38.031],zoom:11};
  const move=async view=>page.evaluate(view=>window.__testMap.jumpTo(view),view);
  const title=async text=>page.waitForFunction(text=>document.querySelector('#map-title-text').textContent===text,text);
  const settled=async()=>page.waitForFunction(()=>getComputedStyle(document.querySelector('.brand-copy')).opacity==='1'&&getComputedStyle(document.querySelector('#panel-content')).opacity==='1');
  await move(ragged);await title('Ragged Mountain Trails');await settled();
  await page.locator('#map-title').click();
  await page.evaluate(()=>{
    window.__panelFrames=[];
    window.__recordPanel=true;
    const sample=()=>{
      if(!window.__recordPanel)return;
      window.__panelFrames.push({title:document.querySelector('#map-title-text').textContent,panel:document.querySelector('#panel-title').textContent,
        titleOpacity:Number(getComputedStyle(document.querySelector('.brand-copy')).opacity),
        headingOpacity:Number(getComputedStyle(document.querySelector('.panel-heading > div')).opacity),
        contentOpacity:Number(getComputedStyle(document.querySelector('#panel-content')).opacity)});
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
    window.__testMap.getCanvas().focus();
  });
  await move(monticello);await title('Saunders–Monticello Trails');await settled();
  assert.equal(await page.locator('#panel-title').textContent(),'Saunders–Monticello');
  assert.match(await page.locator('#panel-content').textContent(),/winding path/);
  assert.match(await page.locator('.info-sources > .source-link').first().getAttribute('href'),/monticello.org/);
  assert.equal(await page.evaluate(()=>document.activeElement===window.__testMap.getCanvas()),true,'automatic refresh keeps map focus');

  // A second context arrives before the first fade-out finishes.
  await page.evaluate(({first,last})=>{
    const copy=document.querySelector('.brand-copy');
    const observer=new MutationObserver(()=>{
      if(copy.classList.contains('is-changing')){
        observer.disconnect();setTimeout(()=>window.__testMap.jumpTo(last),40);
      }
    });
    observer.observe(copy,{attributes:true,attributeFilter:['class']});
    window.__testMap.jumpTo(first);
  },{first:ragged,last:overview});
  await title('Cville Trails');await settled();
  assert.equal(await page.locator('#panel-title').textContent(),'Cville Trails');
  assert.match(await page.locator('#panel-content').textContent(),/Find your way around/);
  await move(ragged);await title('Ragged Mountain Trails');await settled();
  assert.equal(await page.locator('#panel-title').textContent(),'Ragged Mountain');
  const frames=await page.evaluate(()=>{window.__recordPanel=false;return window.__panelFrames;});
  const names={'Ragged Mountain Trails':'Ragged Mountain','Saunders–Monticello Trails':'Saunders–Monticello','Cville Trails':'Cville Trails'};
  assert.ok(frames.some(f=>f.titleOpacity>0&&f.titleOpacity<0.95),'fade is visible');
  for(const f of frames){
    assert.equal(f.panel,names[f.title],'title and panel always describe the same system');
    assert.ok(Math.abs(f.titleOpacity-f.headingOpacity)<0.02&&Math.abs(f.titleOpacity-f.contentOpacity)<0.02,'title, heading, and content fade together');
  }

  await page.setViewportSize({width:390,height:844});
  await page.emulateMedia({reducedMotion:'reduce'});
  await move(monticello);await title('Saunders–Monticello Trails');
  assert.equal(await page.locator('#panel-title').textContent(),'Saunders–Monticello');
  assert.equal(await page.locator('#panel-content').evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
  assert.equal(await page.locator('.is-changing').count(),0);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:'test-results/context-panel-mobile.png'});
  await page.emulateMedia({reducedMotion:'no-preference'});

  // Closing during the fade must not reopen the panel when the timer fires.
  await page.evaluate(view=>{
    const copy=document.querySelector('.brand-copy');
    const observer=new MutationObserver(()=>{
      if(copy.classList.contains('is-changing')){observer.disconnect();document.querySelector('#close-panel').click();}
    });
    observer.observe(copy,{attributes:true,attributeFilter:['class']});
    window.__testMap.jumpTo(view);
  },ragged);
  await title('Ragged Mountain Trails');await settled();
  assert.equal(await page.locator('#panel').isVisible(),false);
  await page.locator('#map-title').click();
  assert.equal(await page.locator('#panel-title').textContent(),'Ragged Mountain');

  // Opening Updates during a context transition must keep that explicit view.
  await page.evaluate(view=>{
    const copy=document.querySelector('.brand-copy');
    const observer=new MutationObserver(()=>{
      if(copy.classList.contains('is-changing')){observer.disconnect();document.querySelector('#updates').click();}
    });
    observer.observe(copy,{attributes:true,attributeFilter:['class']});
    window.__testMap.jumpTo(view);
  },monticello);
  await title('Saunders–Monticello Trails');await settled();
  assert.equal(await page.locator('#panel-title').textContent(),'Trail updates');
  assert.equal(await page.locator('#update-scope').isVisible(),true);
  assert.equal(await page.locator('#panel.is-changing').count(),0);

  // The overview directory covers each named system and keeps its details open
  // even for wide networks, polygon centers, and small mobile viewports.
  const systems=await page.evaluate(async()=>await(await fetch('data/systems.json')).json());
  const destinations=systems.filter(s=>s.context_mode).sort((a,b)=>a.name.localeCompare(b.name));
  await page.emulateMedia({reducedMotion:'reduce'});
  for(const viewport of [{width:1200,height:900},{width:390,height:844}]){
    await page.setViewportSize(viewport);
    for(const id of ['ragged-mountain','rivanna','ivy-creek-natural-area','jordan-park','wintergreen','dcr-high-bridge-trail-state-park']){
      const system=systems.find(s=>s.id===id);
      await move(overview);await title('Cville Trails');
      await page.locator('#map-title').click();
      assert.deepEqual(await page.locator('.system-list button').allTextContents(),destinations.map(s=>s.name));
      if(id==='ragged-mountain')await page.screenshot({path:`test-results/system-list-${viewport.width}.png`});
      const button=page.getByRole('button',{name:system.name,exact:true});
      await button.focus();
      await page.keyboard.press('Enter');
      await title(system.context_title||system.name);
      assert.equal(await page.locator('#panel').isVisible(),true);
      assert.equal(await page.locator('#panel-title').textContent(),system.name);
      assert.equal(await page.locator('#close-panel').evaluate(el=>el===document.activeElement),true);
      const framing=await page.evaluate(bounds=>{
        const map=window.__testMap,panel=document.querySelector('#panel').getBoundingClientRect();
        const corners=[map.project([bounds[0],bounds[1]]),map.project([bounds[2],bounds[3]])];
        return {corners,padding:map.getPadding(),fits:corners.every(p=>p.x>=0&&p.x<=innerWidth&&p.y>=89&&p.y<=innerHeight-100
          &&(innerWidth<=600?p.y<panel.top:p.x>panel.right))};
      },system.bounds);
      assert.ok(framing.fits,`${id} fits in the unobscured map at ${viewport.width}px: ${JSON.stringify(framing)}`);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      if(id==='ragged-mountain')await page.screenshot({path:`test-results/system-selected-${viewport.width}.png`});
    }
  }
  // Subsequent browsing returns to automatic context selection.
  await move(monticello);await title('Saunders–Monticello Trails');
  assert.equal(await page.locator('#panel-title').textContent(),'Saunders–Monticello');
  await page.locator('#close-panel').click();
  await move(overview);await title('Cville Trails');
  assert.equal(await page.locator('#panel').isVisible(),false);
  assert.deepEqual(errors,[]);
  console.log('Context panel checks passed: synchronized fades, overview directory, selected-system framing and details, keyboard navigation, automatic context reset, mobile, reduced motion, close during fade, and Updates view.');
}finally{await browser.close();}
