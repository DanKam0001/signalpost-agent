const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8030/company/929941551?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  // Official website section is the 4th "Sources checked" - the one with (4)
  const allDetails = page.locator('details:has(summary:has-text("Sources"))');
  const count = await allDetails.count();
  for (let i = 0; i < count; i++) {
    const summary = await allDetails.nth(i).locator('summary').textContent();
    if (summary.includes('(4)')) {
      await allDetails.nth(i).evaluate(d => d.open = true);
      const text = await allDetails.nth(i).innerText();
      console.log('website sources text:\n', text);
      await allDetails.nth(i).scrollIntoViewIfNeeded();
    }
  }
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/38-websoures-open-desktop.png' });
  await browser.close();
})();
