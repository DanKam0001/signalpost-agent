const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  const bad = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('a, button, input, select'));
    return els.filter(el => {
      const r = el.getBoundingClientRect();
      return r.height > 0 && r.height < 40;
    }).map(el => ({ tag: el.tagName, id: el.id, h: el.getBoundingClientRect().height }));
  });
  console.log('elements still under 40px:', JSON.stringify(bad));

  const fileInput = await page.evaluate(() => {
    const el = document.getElementById('batch-file');
    const r = el.getBoundingClientRect();
    return { height: r.height, width: r.width };
  });
  console.log('batch-file input rect:', JSON.stringify(fileInput));

  await page.screenshot({ path: './evidence/stage-1/ui/19-fix-filetap-phone.png' });

  // full page + desktop sanity check too
  await page.screenshot({ path: './evidence/stage-1/ui/19-fix-batch-full-phone.png', fullPage: true });

  const context2 = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page2 = await context2.newPage();
  await page2.goto('http://127.0.0.1:8000/batch', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(400);
  await page2.screenshot({ path: './evidence/stage-1/ui/19-fix-batch-desktop.png' });

  await browser.close();
})();
