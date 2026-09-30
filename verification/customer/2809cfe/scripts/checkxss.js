const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  let xssTriggered = false;
  await page.exposeFunction('__xssCheck', () => { xssTriggered = true; });
  await page.goto('http://127.0.0.1:8003/company/810059672?source=batch', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  const windowFlags = await page.evaluate(() => ({
    desc: window.__xss_description || false,
    footer: window.__xss_footer || false,
    body: window.__xss_body || false,
    img: window.__xss_img || false,
  }));
  console.log('XSS window flags (should all be false/undefined):', windowFlags);

  // Check that the raw text appears escaped in the DOM (as text, not tags)
  const bodyHTML = await page.content();
  const hasRawScriptTag = /<script>window\.__xss_description/.test(bodyHTML);
  console.log('Raw unescaped <script> found in page HTML (BAD if true):', hasRawScriptTag);

  const visibleText = await page.locator('body').innerText();
  console.log('Description text visible literally:', visibleText.includes('We build & sell widgets for you.') || visibleText.includes('We build &amp; sell'));
  console.log('Snippet around description:', visibleText.split('\n').filter(l => l.includes('widgets') || l.includes('build')).join(' | '));

  await page.screenshot({ path: './evidence/stage-1/ui/17-xss-escaping-desktop.png', fullPage: true });
  await browser.close();
})();
