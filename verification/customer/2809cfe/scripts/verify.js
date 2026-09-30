const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const OUT = './evidence/stage-1/ui';
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 375, height: 812 };

const log = [];
function record(entry) { log.push(entry); console.log(JSON.stringify(entry)); }

async function shot(page, name) {
  const p = path.join(OUT, name + '.png');
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function checkNoHorizontalScroll(page) {
  return await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
}

async function checkTapTargets(page) {
  return await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('a, button, input, select'));
    const bad = [];
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue; // hidden
      if (r.height > 0 && r.height < 40) bad.push({ tag: el.tagName, text: (el.textContent||'').trim().slice(0,30), h: r.height });
    }
    return bad;
  });
}

async function run() {
  const browser = await chromium.launch();
  fs.mkdirSync(OUT, { recursive: true });

  for (const [label, viewport] of [['desktop', DESKTOP], ['phone', PHONE]]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
    page.on('pageerror', err => consoleErrors.push(String(err)));

    // 1. Empty start state
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await shot(page, `01-empty-start-${label}`);
    const noScroll1 = await checkNoHorizontalScroll(page);
    record({ entry: 'empty-start', label, noHorizScroll: noScroll1, consoleErrors: [...consoleErrors] });

    // 2. Validation error - non-digits
    const input = page.locator('input[type="text"], input[type="search"], input:not([type])').first();
    await input.fill('abc');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(500);
    await shot(page, `02-validation-nondigits-${label}`);
    const bodyText2 = await page.locator('body').innerText();
    record({ entry: 'validation-nondigits', label, hasErrorText: /invalid|error|digit/i.test(bodyText2) });

    // 3. Validation error - wrong length
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await input.fill('12345678');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(500);
    await shot(page, `03-validation-wronglength-${label}`);
    const bodyText3 = await page.locator('body').innerText();
    record({ entry: 'validation-wronglength', label, hasErrorText: /invalid|error|digit|length/i.test(bodyText3) });

    // 4. Validation error - bad check digit
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await input.fill('123456789');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(500);
    await shot(page, `04-validation-checkdigit-${label}`);
    const bodyText4 = await page.locator('body').innerText();
    record({ entry: 'validation-checkdigit', label, hasErrorText: /invalid|error|check/i.test(bodyText4) });

    // 5. Loading + 6. Available profile - Equinor (923609016)
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await input.fill('923609016');
    const navPromise = page.waitForURL('**/company/923609016**', { timeout: 15000 }).catch(()=>{});
    await page.keyboard.press('Enter');
    // try to catch loading state quickly
    await page.waitForTimeout(150);
    try { await shot(page, `05-loading-${label}`); } catch(e) {}
    await navPromise;
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await shot(page, `06-available-equinor-${label}`);
    const bodyText6 = await page.locator('body').innerText();
    record({ entry: 'available-equinor', label, hasName: /EQUINOR/i.test(bodyText6), url: page.url() });

    // Hover/focus highlight + source link check
    const claimEls = await page.locator('[data-claim-id]').count();
    record({ entry: 'claim-count-equinor', label, count: claimEls });
    if (claimEls > 0) {
      const firstClaim = page.locator('[data-claim-id]').first();
      await firstClaim.scrollIntoViewIfNeeded();
      await firstClaim.hover();
      await page.waitForTimeout(300);
      await shot(page, `07-hover-highlight-equinor-${label}`);
      const sourceLinks = await page.locator('a[data-evidence-id]').count();
      record({ entry: 'source-links-equinor', label, count: sourceLinks });
    }

    // Section badges, summary, changes, unknowns
    const sectionsText = await page.locator('body').innerText();
    record({
      entry: 'sections-summary-check', label,
      hasSummary: /summary|what it does|overview/i.test(sectionsText),
      hasUnknown: /unknown/i.test(sectionsText),
      hasChanged: /change/i.test(sectionsText),
    });

    // 8. Small company - Sandnes Elektriske (partial-ish, historical name)
    await page.goto(BASE + '/company/810034882', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await shot(page, `08-available-sandnes-${label}`);

    // 9. not_available - no such company
    await page.goto(BASE + '/company/999999999', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await shot(page, `09-not-available-999999999-${label}`);
    const bodyText9 = await page.locator('body').innerText();
    record({ entry: 'not-available-nosuchcompany', label, hasMessage: /not.*available|no.*found|does not exist|not found/i.test(bodyText9) });

    // 10. not_available/bankrupt - 935567645
    await page.goto(BASE + '/company/935567645', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await shot(page, `10-bankrupt-935567645-${label}`);
    const bodyText10 = await page.locator('body').innerText();
    record({ entry: 'bankrupt-company', label, hasBankruptcyMention: /bankrupt|konkurs/i.test(bodyText10) });

    // 11. Compare view
    await page.goto(BASE + '/compare?orgnr=923609016&orgnr=810034882', { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    await shot(page, `11-compare-${label}`);
    const bodyText11 = await page.locator('body').innerText();
    record({ entry: 'compare-view', label, hasEquinor: /EQUINOR/i.test(bodyText11), hasSandnes: /SANDNES/i.test(bodyText11) });

    // 12. Batch browser
    await page.goto(BASE + '/batch', { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    await shot(page, `12-batch-${label}`);
    const bodyText12 = await page.locator('body').innerText();
    record({ entry: 'batch-browser', label, rowCountHint: (bodyText12.match(/\d+/g) || []).length });

    // Tap target check (phone only)
    if (label === 'phone') {
      const bad = await checkTapTargets(page);
      record({ entry: 'tap-targets-under-40px', label, bad });
    }

    // Keyboard nav check on lookup page
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => document.activeElement.tagName + ':' + (document.activeElement.className||''));
    record({ entry: 'keyboard-nav-first-tab', label, focused });

    record({ entry: 'final-console-errors', label, consoleErrors: [...consoleErrors] });
    await context.close();
  }

  await browser.close();
  fs.writeFileSync('./verification/customer/2809cfe/run-log.json', JSON.stringify(log, null, 2));
}

run().catch(e => { console.error(e); process.exit(1); });
