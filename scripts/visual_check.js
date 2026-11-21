// Visual check (development only): drives the running app in Chromium and takes screenshots of the
// empty ticket, a half-filled ticket, a result with three proofs and the "None yet" state.
// Usage: node scripts/visual_check.js <out-dir> [base-url] [widths]
//   e.g. node scripts/visual_check.js shots http://127.0.0.1:8765/ 1440,1024,390
const { chromium } = require('playwright');
const OUT = process.argv[2] || 'shots';
const URL = process.argv[3] || 'http://127.0.0.1:8765/';
const widths = (process.argv[4] || '1440,1024,390').split(',').map(Number);
const fs = require('fs');
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const b = await chromium.launch();
  let failed = false;
  for (const W of widths) {
    const p = await b.newPage({ viewport: { width: W, height: W < 500 ? 844 : 1000 }, deviceScaleFactor: 1 });
    const errs = [];
    p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
    p.on('pageerror', (e) => errs.push(String(e)));
    const pick = async (text) => { await p.locator('.tf--active .choice', { hasText: text }).first().click(); await p.waitForTimeout(400); };
    const stamp = async () => { await p.click('.tf--active button:has-text("Stamp")'); await p.waitForTimeout(400); };
    const tail = async () => {
      if (await p.locator('.tf--active h2', { hasText: 'compare' }).count()) await pick('No');
      await pick('No'); await pick('Factual'); await p.waitForTimeout(2600);
    };
    await p.goto(URL); await p.waitForTimeout(1200);
    await p.screenshot({ path: `${OUT}/${W}-1-empty.png` });

    await p.fill('.tf--active input.search', 'textile'); await p.waitForTimeout(150);
    await pick('Clothing and textile'); await pick('Consumers'); await pick('Product label'); await pick('Recycled content');
    await p.screenshot({ path: `${OUT}/${W}-2-half.png` });

    await p.click('#btn-new'); await p.waitForTimeout(700);
    await p.fill('.tf--active input.search', 'company'); await p.waitForTimeout(150);
    await pick('Company as a whole'); await pick('Consumers'); await pick('Advertising'); await pick('Climate neutral or offset');
    await pick('Whole company'); await pick('Internal measurement');
    await p.selectOption('#fact-project_type', 'reforestation'); await p.fill('#fact-Y', '1200'); await stamp();
    await tail();
    const n = await p.locator('.proof').count();
    await p.screenshot({ path: `${OUT}/${W}-3-result.png`, fullPage: true });
    await p.screenshot({ path: `${OUT}/${W}-3-result-top.png` });

    await p.click('#btn-new'); await p.waitForTimeout(700);
    await p.fill('.tf--active input.search', 'packing'); await p.waitForTimeout(150);
    await pick('Packing material'); await pick('Consumers'); await pick('Advertising'); await pick('Recycled content');
    await pick('Packaging only'); await stamp(); await pick('None yet'); await stamp(); await tail();
    await p.screenshot({ path: `${OUT}/${W}-4-noneyet.png`, fullPage: true });
    const hscroll = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    console.log(W, 'proofs', n, 'horizontal scroll', hscroll, 'console errors', JSON.stringify(errs));
    if (hscroll || errs.length || n < 3) failed = true;
    await p.close();
  }
  await b.close();
  process.exit(failed ? 1 : 0);
})();
