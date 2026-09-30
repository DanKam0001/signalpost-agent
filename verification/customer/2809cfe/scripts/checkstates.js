const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const scenarios = [
    ['ambiguous', '810034882'],
    ['blocked', '810059672'],
  ];
  for (const [label, viewport] of [['desktop', {width:1280,height:800}], ['phone', {width:375,height:812}]]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    for (const [state, orgnr] of scenarios) {
      await page.goto(`http://127.0.0.1:8001/company/${orgnr}?source=batch`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(500);
      await page.screenshot({ path: `./evidence/stage-1/ui/15-${state}-${orgnr}-${label}.png`, fullPage: true });
      const text = await page.locator('body').innerText();
      console.log(state, label, text.slice(0,50).replace(/\n/g,' '));
    }
    await context.close();
  }
  await browser.close();
})();
