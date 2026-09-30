const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8010/company/923609016', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const citeInfo = await page.evaluate(() => {
    // find citation buttons within summary - likely [n] superscript links/buttons
    const candidates = Array.from(document.querySelectorAll('.summary button, .summary a, [class*="cite"], sup button, sup a'));
    return candidates.slice(0,8).map(el => {
      const r = el.getBoundingClientRect();
      return { tag: el.tagName, text: el.textContent.trim(), w: r.width, h: r.height, cls: el.className };
    });
  });
  console.log(JSON.stringify(citeInfo, null, 2));
  await page.screenshot({ path: './evidence/stage-1/ui/20-f3-citations-phone.png', fullPage: false });
  // click a citation to check it highlights/scrolls to source
  const firstCite = page.locator('.summary button, .summary a[href^="#"], sup button, sup a').first();
  if (await firstCite.count() > 0) {
    await firstCite.click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: './evidence/stage-1/ui/21-f3-citation-clicked-phone.png' });
  }
  await browser.close();
})();
