const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8021/company/810059672?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const el = page.locator('[data-field="official_website"]').first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.hover('[data-field="official_website"]');
  await page.waitForTimeout(300);
  await page.screenshot({ path: './evidence/stage-1/ui/33-refresh-status-zoom-desktop.png' });
  const html = await el.innerHTML();
  console.log(html);
  await browser.close();
})();
