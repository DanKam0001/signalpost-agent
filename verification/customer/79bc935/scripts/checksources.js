const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));

    for (const orgnr of ['929941551', '818037562']) {
      await page.goto(`http://127.0.0.1:8030/company/${orgnr}?source=batch`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(500);
      const detailsCount = await page.locator('details.sources, details:has(summary:has-text("Sources"))').count();
      console.log(label, orgnr, 'sources <details> count:', detailsCount);
      const summaries = await page.locator('summary').allTextContents();
      console.log(label, orgnr, 'summaries:', JSON.stringify(summaries.filter(s => /Sources/i.test(s))));
      console.log(label, orgnr, 'console errors:', JSON.stringify(errors));
    }
    await ctx.close();
  }
  await browser.close();
})();
