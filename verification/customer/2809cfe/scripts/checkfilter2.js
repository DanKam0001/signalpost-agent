const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/batch', { waitUntil: 'networkidle' });
  const stateSelect = page.locator('select');
  const opts = await stateSelect.locator('option').allTextContents();
  console.log('state options:', opts);
  await stateSelect.selectOption({ label: 'Available' });
  await page.waitForTimeout(400);
  const text = await page.locator('body').innerText();
  console.log(text.match(/\d+ of \d+ companies/)[0]);
  await browser.close();
})();
