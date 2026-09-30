const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });
  // realistic: page loads, input already focused per app design; user types immediately
  await page.keyboard.type('923609016');
  await page.keyboard.press('Enter');
  await page.waitForURL('**/company/923609016**', { timeout: 10000 });
  console.log('Realistic keyboard-only journey OK, landed at:', page.url());
  await browser.close();
})();
