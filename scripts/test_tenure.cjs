// Serve the repo: python3 -m http.server 8765 --bind 127.0.0.1
// Run with Playwright installed: node scripts/test_tenure.cjs
// Optional: TENURE_URL, TENURE_EVIDENCE, TENURE_BASELINE; --baseline records the old UI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const baseline = process.argv.includes('--baseline');
  const output = process.env.TENURE_EVIDENCE;
  const previous = process.env.TENURE_BASELINE
    ? JSON.parse(fs.readFileSync(process.env.TENURE_BASELINE, 'utf8')) : null;
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.clock.install({ time: new Date('2026-10-11T12:00:00Z') });
    await page.goto(process.env.TENURE_URL || 'http://127.0.0.1:8765');
    await page.locator('#appTabTenure').click();
    const snapshots = {};
    const money = value => '$' + Math.round(value).toLocaleString('en-US');
    let checks = 0;
    for (const scenario of [
      { name: 'percent', growth: 'percent', pct: 12, base: 10000 },
      { name: 'multiple', growth: 'multiple', pct: 12, base: 10000 },
      { name: 'zero-growth', growth: 'percent', pct: 0, base: 1234 },
      { name: 'zero-base', growth: 'percent', pct: 12, base: 0 },
    ]) {
      await page.locator(`[data-gm="${scenario.growth}"]`).click();
      await page.locator('#t-base').fill(String(scenario.base));
      if (scenario.growth === 'percent') await page.locator('#t-pct').fill(String(scenario.pct));
      await page.locator('#t-syear').fill('2024');
      await page.locator('#t-smonth').selectOption('12');
      for (const period of ['year', 'month', 'week']) {
        await page.locator(`[data-pf="${period}"]`).click();
        for (const view of ['year', 'month']) {
          await page.locator(`[data-vu="${view}"]`).click();
          const key = `${scenario.name}-${period}-${view}`;
          const result = await page.evaluate(() => ({
            headers: [...document.querySelectorAll('#t-thead th')].map(el => el.textContent),
            rows: [...document.querySelectorAll('#t-tbody tr')].map(tr => [...tr.cells].map(el => el.textContent)),
            labels: [...document.querySelector('#t-tbody tr').cells].map(el => el.dataset.label),
            totals: ['t-total-val', 't-since-val', 't-req'].map(id => document.getElementById(id).textContent),
          }));
          snapshots[key] = result;
          const headers = view === 'year'
            ? ['Year', 'Calendar', 'Year', 'Month', 'Week', 'Day', 'Total']
            : ['Month', 'Calendar', 'Yr', 'Month', 'Year', 'Total'];
          const rows = baseline ? result.rows.map(row => row.filter((_, i) => i !== (view === 'year' ? 2 : 3))) : result.rows;
          if (!baseline) {
            assert.deepEqual(result.headers, headers, key);
            assert.deepEqual(result.labels, headers, `${key} cell labels`);
            if (previous) {
              const old = previous[key];
              assert.deepEqual(result.rows, old.rows.map(row => row.filter((_, i) => i !== (view === 'year' ? 2 : 3))), `${key} retained values`);
              assert.deepEqual(result.totals, old.totals, `${key} banners and solver unchanged`);
            }
          }
          const ppy = { year: 1, month: 12, week: 52 }[period];
          let cumulative = 0;
          assert.equal(rows.length, view === 'year' ? 15 : 24);
          rows.forEach((row, index) => {
            const ordinal = index + 1;
            const tenureYear = view === 'year' ? ordinal : Math.ceil(ordinal / 12);
            const rate = scenario.growth === 'multiple' ? scenario.base * tenureYear : scenario.base * (1 + scenario.pct / 100) ** (tenureYear - 1);
            const annual = rate * ppy;
            cumulative += view === 'year' ? annual : annual / 12;
            const date = new Date(2024, 11 + (view === 'year' ? index * 12 : index), 1);
            const calendar = date.toLocaleString('en-US', { month: 'short' }) + ' ' + date.getFullYear();
            const expected = view === 'year'
              ? [String(ordinal), calendar, money(annual), money(annual / 12), money(annual / 52), money(annual / 365), money(cumulative)]
              : [String(ordinal), calendar, String(tenureYear), money(annual / 12), money(annual), money(cumulative)];
            assert.deepEqual(row, expected, `${key} row ${ordinal}`);
          });
          assert.equal(result.totals[0], money(cumulative), `${key} banner`);
          checks++;
          if (output && scenario.name === 'percent') {
            fs.mkdirSync(output, { recursive: true });
            for (const width of [1000, 390]) {
              await page.setViewportSize({ width, height: 900 });
              await page.locator('[data-pf="year"]').scrollIntoViewIfNeeded();
              await page.evaluate(() => {
                const section = document.querySelector('[data-pf="year"]').closest('.section');
                window.scrollTo(0, section.getBoundingClientRect().top + window.scrollY - 16);
              });
              assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${key} page overflow at ${width}`);
              await page.screenshot({ path: path.join(output, `${baseline ? 'before' : 'after'}-${period}-${view}-${width}.png`) });
              const scroll = await page.evaluate(() => {
                const wrap = document.querySelector('#app-tenure .t-table-wrap');
                wrap.scrollLeft = wrap.scrollWidth;
                const first = document.querySelector('#t-tbody tr td:first-child').getBoundingClientRect();
                const last = document.querySelector('#t-tbody tr td:last-child').getBoundingClientRect();
                const bounds = wrap.getBoundingClientRect();
                const visible = first.left >= bounds.left - 1 && last.right <= bounds.right + 1;
                wrap.scrollLeft = 0;
                return visible;
              });
              assert.ok(scroll, `${key} ordinal and total accessible when scrolled at ${width}`);
            }
          }
        }
      }
    }
    assert.deepEqual(errors, [], 'browser errors');
    if (output) fs.writeFileSync(path.join(output, `${baseline ? 'before' : 'after'}.json`), JSON.stringify(snapshots, null, 2));
    console.log(`PASS: ${checks} cases; all rows, dates, totals, growth modes and pay frequencies; no browser errors${previous ? '; retained values and solver match baseline' : ''}.`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
