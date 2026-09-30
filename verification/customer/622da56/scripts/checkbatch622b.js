const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto('http://127.0.0.1:8020/batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const text = await page.locator('body').innerText();
    console.log(label, 'batch count line:', text.match(/\d+ of \d+ companies/)?.[0]);
    await page.screenshot({ path: `./evidence/stage-1/ui/28-recheck-batch-${label}.png`, fullPage: true });

    const link = page.locator('main a[href*="/company/"]').first();
    const href = await link.getAttribute('href');
    await link.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(400);
    console.log(label, 'clicked href:', href, '-> landed at:', page.url());
    console.log(label, 'console/page errors:', JSON.stringify(errors));
    await ctx.close();
  }
  await browser.close();
})();
