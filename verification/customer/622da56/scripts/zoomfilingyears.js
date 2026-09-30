const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8020/company/925691798?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const el = page.locator('text=Latest annual accounts and history').first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/30-filingyears-zoom-desktop.png' });
  await browser.close();
})();
