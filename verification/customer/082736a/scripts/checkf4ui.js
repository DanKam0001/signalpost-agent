const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8012/company/810105372?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  console.log('console/page errors:', JSON.stringify(errors));
  await page.screenshot({ path: './evidence/stage-1/ui/25-f4-blocked-source-desktop.png', fullPage: true });
  const text = await page.locator('body').innerText();
  console.log('shows Blocked badge:', /Blocked/.test(text));
  await browser.close();
})();
