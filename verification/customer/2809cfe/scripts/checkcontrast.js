const { chromium } = require('playwright');

function luminance(r,g,b){
  const a=[r,g,b].map(v=>{v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4);});
  return a[0]*0.2126+a[1]*0.7152+a[2]*0.0722;
}
function parseColor(str){
  const m = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if(!m) return null;
  return [parseInt(m[1]),parseInt(m[2]),parseInt(m[3])];
}
function contrast(c1,c2){
  const l1=luminance(...c1)+0.05, l2=luminance(...c2)+0.05;
  return l1>l2? l1/l2 : l2/l1;
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8000/company/923609016', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);

  const targets = ['body', 'header.top', '.brand', 'footer.foot', '[class*="badge"]', '[class*="available"]', '[class*="failed"]', 'a'];
  for (const sel of targets) {
    const els = await page.$$(sel);
    for (const el of els.slice(0,2)) {
      const info = await el.evaluate(e => {
        const cs = getComputedStyle(e);
        return { color: cs.color, bg: cs.backgroundColor, text: (e.textContent||'').trim().slice(0,20) };
      });
      let bgColor = info.bg;
      // walk up if transparent
      let cur = el;
      let bgc = parseColor(info.bg);
      let depth = 0;
      while ((!bgc || info.bg === 'rgba(0, 0, 0, 0)') && depth < 5) {
        cur = await cur.evaluateHandle(e => e.parentElement);
        if (!cur) break;
        const bgInfo = await cur.evaluate(e => getComputedStyle(e).backgroundColor).catch(()=>null);
        if (bgInfo && bgInfo !== 'rgba(0, 0, 0, 0)') { bgc = parseColor(bgInfo); break; }
        depth++;
      }
      const fgc = parseColor(info.color);
      if (fgc && bgc) {
        const ratio = contrast(fgc, bgc);
        console.log(sel, '|', info.text, '| fg', info.color, 'bg-effective', bgc, '| ratio', ratio.toFixed(2), ratio >= 4.5 ? 'PASS' : 'LOW');
      }
    }
  }
  await browser.close();
})();
