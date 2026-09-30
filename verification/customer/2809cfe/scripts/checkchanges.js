const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, viewport] of [['desktop', {width:1280,height:800}], ['phone', {width:375,height:812}]]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8002/company/810034882?source=batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    await page.screenshot({ path: `./evidence/stage-1/ui/16-whatchanged-${label}.png`, fullPage: true });
    await context.close();
  }
  await browser.close();
})();
