const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const pages = [
    '/', '/company/923609016', '/company/923609016?source=batch',
    '/compare?orgnr=923609016&orgnr=810034882', '/batch', '/company/abc'
  ];
  for (const path of pages) {
    await page.goto('http://127.0.0.1:8010' + path, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    const result = await page.evaluate(() => {
      const els = Array.from(document.querySelectorAll('main a, main button, main summary, a, button, input, select, summary, [tabindex]'));
      const bad = [];
      for (const el of els) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        if (r.height > 0 && (r.height < 40 || r.width < 40)) {
          bad.push({ tag: el.tagName, text: (el.textContent||'').trim().slice(0,25), w: r.width, h: r.height });
        }
      }
      return { badCount: bad.length, bad: bad.slice(0,10), scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth };
    });
    console.log(path, '-> under40:', result.badCount, 'scrollOK:', result.scrollWidth <= result.clientWidth + 1, result.bad);
  }
  await browser.close();
})();
