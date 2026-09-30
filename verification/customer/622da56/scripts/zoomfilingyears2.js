const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8020/company/925691798?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  // expand the "Show 10 more" / any details within the accounts section to reveal filing_years claim
  await page.evaluate(() => document.querySelectorAll('details').forEach(d => d.open = true));
  await page.waitForTimeout(200);
  const el = page.locator('.fact.unavailable, .fact[data-field="filing_years"]').first();
  const count = await page.locator('[data-field="filing_years"]').count();
  console.log('filing_years fact elements found:', count);
  if (count > 0) {
    await page.locator('[data-field="filing_years"]').first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  }
  await page.screenshot({ path: './evidence/stage-1/ui/31-filingyears-claim-desktop.png' });
  const html = await page.locator('[data-field="filing_years"]').first().innerHTML().catch(()=>'NOT FOUND');
  console.log('filing_years HTML:', html.slice(0,500));
  await browser.close();
})();
