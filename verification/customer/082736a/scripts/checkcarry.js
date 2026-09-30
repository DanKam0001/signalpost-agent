const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const context = await browser.newContext({ viewport: vp });
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8011/company/810059672?source=batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    await page.screenshot({ path: `./evidence/stage-1/ui/22-carried-forward-${label}.png`, fullPage: true });
    const text = await page.locator('body').innerText();
    console.log(label, 'mentions carried/not refreshed/not refetched:', /carried|not refreshed|not refetched|last supported/i.test(text));
    await context.close();
  }
  await browser.close();
})();
