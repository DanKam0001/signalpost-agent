const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto('http://127.0.0.1:8031/company/810059672?source=batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const text = await page.locator('body').innerText();
    console.log(label, 'contains "Not refreshed this run":', text.includes('Not refreshed this run'));
    const factHTML = await page.locator('[data-field="official_website"]').first().innerHTML();
    console.log(label, 'fact row HTML:', factHTML);
    console.log(label, 'console errors:', JSON.stringify(errors));
    await page.locator('[data-field="official_website"]').first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
    await page.screenshot({ path: `./evidence/stage-1/ui/43-carriedtag-${label}.png`, fullPage: true });
    await ctx.close();
  }
  await browser.close();
})();
