const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto('http://127.0.0.1:8020/company/925691798?source=batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    console.log(label, 'console/page errors:', JSON.stringify(errors));
    const text = await page.locator('body').innerText();
    const hasReason = text.includes('Brønnøysund limits this endpoint to about 30 requests per minute');
    console.log(label, 'filing-years blocked reason visible:', hasReason);
    const scrollOK = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
    console.log(label, 'no horizontal scroll:', scrollOK);
    await page.screenshot({ path: `./evidence/stage-1/ui/29-filingyears-blocked-${label}.png`, fullPage: true });
    await ctx.close();
  }
  await browser.close();
})();
