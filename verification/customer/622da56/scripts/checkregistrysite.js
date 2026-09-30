const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8020/company/818037562?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const scrollOK = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  console.log('no horizontal scroll:', scrollOK);
  const el = page.locator('text=Official website and company-owned').first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/36-registrydeclared-zoom-phone.png' });
  await browser.close();
})();
