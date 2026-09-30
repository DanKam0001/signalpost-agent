const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8030/company/929941551?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);

  const closedByDefault = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('details.sources, details')).filter(d => d.querySelector('summary')?.textContent.includes('Sources')).map(d => d.open);
  });
  console.log('open state of each Sources <details> (should all be false):', JSON.stringify(closedByDefault));

  // find the website section's details (2 sources) and open it
  const allDetails = page.locator('details:has(summary:has-text("Sources"))');
  const count = await allDetails.count();
  for (let i = 0; i < count; i++) {
    const summary = await allDetails.nth(i).locator('summary').textContent();
    if (summary.includes('(2)')) {
      await allDetails.nth(i).evaluate(d => d.open = true);
    }
  }
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/37-sources-open-desktop.png', fullPage: true });

  const html = await allDetails.first().evaluate(d => d.outerHTML);
  console.log('first details outerHTML sample:', html.slice(0, 400));

  // find a zero-count one and open it to check "No sources recorded"
  for (let i = 0; i < count; i++) {
    const summary = await allDetails.nth(i).locator('summary').textContent();
    if (summary.includes('(0)')) {
      await allDetails.nth(i).evaluate(d => d.open = true);
      const text = await allDetails.nth(i).innerText();
      console.log('zero-count details text:', JSON.stringify(text));
      break;
    }
  }

  await browser.close();
})();
