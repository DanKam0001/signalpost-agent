const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8011/company/810059672?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const section = page.locator('text=Official website and company-owned profiles').locator('..');
  const el = await page.locator('h2:has-text("Official website and company-owned profiles"), h3:has-text("Official website and company-owned profiles")').first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/23-carried-zoom-desktop.png', clip: { x: 0, y: await el.evaluate(e=>e.getBoundingClientRect().top+window.scrollY).catch(()=>0), width: 1280, height: 400 } }).catch(async ()=>{
    await page.screenshot({ path: './evidence/stage-1/ui/23-carried-zoom-desktop.png' });
  });

  // hover the official website fact to see Source panel content
  const factRow = page.locator('text=Official website').last();
  await factRow.scrollIntoViewIfNeeded();
  await factRow.hover();
  await page.waitForTimeout(300);
  await page.screenshot({ path: './evidence/stage-1/ui/24-carried-hover-desktop.png' });

  const html = await page.locator('main').innerHTML();
  const idx = html.indexOf('last seen');
  console.log('context around "last seen":', html.slice(Math.max(0,idx-500), idx+200).replace(/\n/g,' '));
  await browser.close();
})();
