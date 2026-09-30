const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/company/921326904', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.screenshot({ path: './evidence/stage-1/ui/13-deleted-921326904-desktop.png', fullPage: true });
  const text = await page.locator('body').innerText();
  console.log('deleted mention:', /delet|slettet/i.test(text));
  console.log(text.slice(0, 600));
  await browser.close();
})();
