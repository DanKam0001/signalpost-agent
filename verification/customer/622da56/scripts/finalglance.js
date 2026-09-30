const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/company/923609016', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const cite = page.locator('.cite').first();
  const box = await cite.boundingBox();
  console.log('first citation box:', JSON.stringify(box));
  await page.screenshot({ path: './evidence/stage-1/ui/26-final-622da56-profile-phone.png', fullPage: true });
  await cite.click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: './evidence/stage-1/ui/27-final-622da56-citation-tap-phone.png' });

  const ctx2 = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page2 = await ctx2.newPage();
  await page2.goto('http://127.0.0.1:8000/company/923609016', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(500);
  await page2.screenshot({ path: './evidence/stage-1/ui/26-final-622da56-profile-desktop.png', fullPage: true });

  await browser.close();
})();
