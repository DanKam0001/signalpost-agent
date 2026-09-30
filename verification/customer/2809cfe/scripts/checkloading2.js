const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, viewport] of [['desktop', {width:1280,height:800}], ['phone', {width:375,height:812}]]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    await page.route('**/api/company/**', async route => {
      await new Promise(r => setTimeout(r, 4000));
      await route.continue();
    });
    await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });
    const input = page.locator('input[type="text"], input:not([type])').first();
    await input.fill('291417779');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(700);
    await page.screenshot({ path: `./evidence/stage-1/ui/14-loading-throttled-${label}.png`, fullPage: true });
    const text = await page.locator('body').innerText();
    console.log(label, 'snippet:', text.slice(0,400).replace(/\n/g,' | '));
    await context.close();
  }
  await browser.close();
})();
