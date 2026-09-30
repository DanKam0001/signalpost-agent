const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8020/company/929941551?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const el = page.locator('text=Official website and company-owned').first();
  await el.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: './evidence/stage-1/ui/35-multicandidate-zoom-phone.png' });

  // check any element overflowing its container horizontally
  const overflow = await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('main *'));
    const bad = [];
    for (const el of all) {
      const r = el.getBoundingClientRect();
      if (r.right > document.documentElement.clientWidth + 1) {
        bad.push({ tag: el.tagName, cls: el.className, text: (el.textContent||'').trim().slice(0,40), right: r.right });
      }
    }
    return bad.slice(0,10);
  });
  console.log('overflowing elements:', JSON.stringify(overflow));
  await browser.close();
})();
