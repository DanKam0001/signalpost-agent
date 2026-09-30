const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8030/company/818037562?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelectorAll('details').forEach(d => d.open = true));
  await page.waitForTimeout(200);
  const el = page.locator('text=Official website and company-owned').first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/40-818037562-websources-zoom-phone.png' });
  const text = await page.locator('body').innerText();
  const idx = text.indexOf('Sources checked');
  console.log(text.slice(text.indexOf('Official website and company'), text.indexOf('Official website and company')+800));
  await browser.close();
})();
