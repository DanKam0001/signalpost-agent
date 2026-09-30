const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8030/company/818037562?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const allDetails = page.locator('details:has(summary:has-text("Sources"))');
  const count = await allDetails.count();
  for (let i = 0; i < count; i++) {
    const summary = await allDetails.nth(i).locator('summary').textContent();
    const el = allDetails.nth(i);
    await el.evaluate(d => d.open = true);
  }
  await page.waitForTimeout(200);
  const scrollOK = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  console.log('818037562 phone, all details open, no horiz scroll:', scrollOK);
  const bad = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('a, button, input, select, summary'));
    return els.filter(el => { const r = el.getBoundingClientRect(); return r.height > 0 && (r.height < 40 || r.width < 40); }).length;
  });
  console.log('818037562 phone, elements under 40px with all details open:', bad);
  await page.screenshot({ path: './evidence/stage-1/ui/39-818037562-sources-open-phone.png', fullPage: true });
  await browser.close();
})();
