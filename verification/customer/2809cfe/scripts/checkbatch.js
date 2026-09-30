const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const scrollInfo = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }));
  console.log('scrollInfo', scrollInfo);
  // screenshot just the viewport (not fullpage) plus first 1600px
  await page.screenshot({ path: '/tmp/batch-phone-top.png' });
  await page.evaluate(() => window.scrollTo(0, 600));
  await page.screenshot({ path: '/tmp/batch-phone-scroll600.png' });
  await browser.close();
})();
