const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8011/company/810059672?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const text = await page.locator('body').innerText();
  console.log('mentions "last seen":', text.includes('last seen'));
  const snippet = text.split('\n').filter(l => l.includes('last seen') || l.includes('Official website')).join(' | ');
  console.log('snippet:', snippet);
  const opacity = await page.locator('.fact.carried').first().evaluate(el => getComputedStyle(el).opacity).catch(()=>'n/a');
  console.log('carried fact opacity:', opacity);
  await browser.close();
})();
