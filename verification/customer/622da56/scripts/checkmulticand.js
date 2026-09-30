const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    await page.goto('http://127.0.0.1:8020/company/929941551?source=batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const scrollOK = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
    console.log(label, 'no horizontal scroll:', scrollOK);
    await page.screenshot({ path: `./evidence/stage-1/ui/34-multicandidate-${label}.png`, fullPage: true });
    await ctx.close();
  }
  await browser.close();
})();
