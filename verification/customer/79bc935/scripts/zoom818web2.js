const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8030/company/818037562?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelectorAll('details').forEach(d => d.open = true));
  await page.waitForTimeout(200);
  const el = page.locator('h2:has-text("Official website and company-owned"), h3:has-text("Official website and company-owned")').first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/41-818037562-websources-section-phone.png' });
  await browser.close();
})();
