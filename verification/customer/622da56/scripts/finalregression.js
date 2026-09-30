const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const pages = ['/', '/compare?orgnr=929941551&orgnr=935830532', '/company/abc'];
  for (const path of pages) {
    await page.goto('http://127.0.0.1:8020' + path, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    const result = await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll('a, button, input, select, summary, [tabindex]'));
      const bad = els.filter(el => {
        const r = el.getBoundingClientRect();
        return r.height > 0 && (r.height < 40 || r.width < 40);
      }).map(el => ({ tag: el.tagName, h: el.getBoundingClientRect().height }));
      return { bad, scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth };
    });
    console.log(path, '-> under40:', result.bad.length, 'noScroll:', result.scrollWidth <= result.clientWidth+1, JSON.stringify(result.bad));
  }
  await browser.close();
})();
