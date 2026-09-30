const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/batch', { waitUntil: 'networkidle' });
  await page.fill('input[placeholder*="Name" i], input[placeholder*="organisation" i]', 'Torvtransport');
  await page.waitForTimeout(400);
  const text1 = await page.locator('body').innerText();
  console.log('FILTER by name -> contains TORVTRANSPORT:', /TORVTRANSPORT/i.test(text1), '| row count guess:', (text1.match(/Org\. no\./g)||[]).length);
  await page.screenshot({ path: '/tmp/batch-filter-name.png', fullPage: true });

  await page.fill('input[placeholder*="Name" i], input[placeholder*="organisation" i]', '');
  const stateSelect = page.locator('select');
  await stateSelect.selectOption({ label: 'Failed' }).catch(async ()=>{
    const opts = await stateSelect.locator('option').allTextContents();
    console.log('options:', opts);
  });
  await page.waitForTimeout(400);
  const text2 = await page.locator('body').innerText();
  console.log('FILTER by state Failed -> row count guess:', (text2.match(/Org\. no\./g)||[]).length);
  await page.screenshot({ path: '/tmp/batch-filter-state.png', fullPage: true });

  await browser.close();
})();
