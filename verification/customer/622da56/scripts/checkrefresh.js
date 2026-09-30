const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto('http://127.0.0.1:8021/company/810059672?source=batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    console.log(label, 'console/page errors:', JSON.stringify(errors));

    // exactly one row for official_website
    const rows = await page.locator('[data-field="official_website"]').count();
    console.log(label, 'official_website rows:', rows);

    const text = await page.locator('body').innerText();
    console.log(label, 'mentions "last seen":', text.includes('last seen'));

    await page.screenshot({ path: `./evidence/stage-1/ui/32-refresh-status-${label}.png`, fullPage: true });
    await ctx.close();
  }
  await browser.close();
})();
