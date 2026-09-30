const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['desktop',{width:1280,height:800}],['phone',{width:375,height:812}]]) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    for (const path of ['/', '/compare?orgnr=923609016&orgnr=810034882', '/company/923609016']) {
      await page.goto('http://127.0.0.1:8000'+path, { waitUntil: 'networkidle' });
      await page.waitForTimeout(300);
      const noScroll = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
      console.log(label, path, 'noHorizScroll:', noScroll);
    }
    await ctx.close();
  }
  await browser.close();
})();
