const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const bad = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('a, button, input, select'));
    return els.filter(el => {
      const r = el.getBoundingClientRect();
      return r.height > 0 && r.height < 40;
    }).map(el => ({ tag: el.tagName, type: el.type, id: el.id, cls: el.className, h: el.getBoundingClientRect().height, outer: el.outerHTML.slice(0,150) }));
  });
  console.log(JSON.stringify(bad, null, 2));
  await browser.close();
})();
