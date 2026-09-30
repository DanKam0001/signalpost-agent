const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/company/923609016', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);

  // Check outbound links rel attribute
  const outboundLinks = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('a[href^="http"]'));
    return links.map(a => ({ href: a.href, rel: a.rel, target: a.target })).slice(0, 20);
  });
  console.log('Sample outbound links:', JSON.stringify(outboundLinks, null, 2));

  const missingRel = outboundLinks.filter(l => !l.rel || !l.rel.includes('noopener') || !l.rel.includes('noreferrer'));
  console.log('Links missing noopener/noreferrer:', missingRel.length, JSON.stringify(missingRel));

  // Check a specific "Registry record" source link href
  const firstSourceLink = await page.locator('a:has-text("Registry record")').first();
  const href = await firstSourceLink.getAttribute('href');
  console.log('First Registry record href:', href);

  await browser.close();
})();
