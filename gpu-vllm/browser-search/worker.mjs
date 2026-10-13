import { chromium } from 'playwright';
import fs from 'node:fs/promises';

const input = JSON.parse(await fs.readFile('/dev/stdin', 'utf8'));
const browser = await chromium.launch({headless: true});
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  if (input.action === 'search') {
    const errors = [];
    let results = [];
    for (const engine of ['duckduckgo', 'bing']) {
      const address = engine === 'duckduckgo'
        ? 'https://html.duckduckgo.com/html/?q=' + encodeURIComponent(input.query)
        : 'https://www.bing.com/search?q=' + encodeURIComponent(input.query);
      try {
        const response = await page.goto(address, {waitUntil: 'domcontentloaded'});
        if (!response?.ok()) throw new Error('HTTP ' + response?.status());
        const selector = engine === 'duckduckgo' ? '.result' : 'li.b_algo';
        await page.locator(selector).first().waitFor({timeout: 10000});
        results = await page.locator(selector).evaluateAll((rows, engine) => rows.map(row => {
          const link = row.querySelector(engine === 'duckduckgo' ? '.result__a' : 'h2 a');
          if (!link) return null;
          let url = link.href;
          if (engine === 'duckduckgo') {
            const redirect = new URL(url).searchParams.get('uddg');
            if (redirect) url = redirect;
          } else {
            const encoded = new URL(url).searchParams.get('u');
            if (encoded?.startsWith('a1')) {
              try { url = atob(encoded.slice(2).replace(/-/g, '+').replace(/_/g, '/')); }
              catch { /* Keep the actual redirect if decoding fails. */ }
            }
          }
          return {title: link.textContent.trim(), url,
            snippet: (row.querySelector(engine === 'duckduckgo' ? '.result__snippet' : '.b_caption')?.textContent ?? '').trim()};
        }).filter(Boolean), engine);
        results = results.filter(r => /^https?:\/\//.test(r.url)).slice(0, input.topn ?? 5);
        if (results.length) break;
        throw new Error('No usable search results');
      } catch (error) { errors.push(engine + ': ' + error.message); }
    }
    if (!results.length) throw new Error('Search failed (including possible bot challenge): ' + errors.join('; '));
    console.log(JSON.stringify({query: input.query, results}));
  } else if (input.action === 'open') {
    if (!/^https?:\/\//.test(input.url)) throw new Error('Only http/https URLs are supported');
    const response = await page.goto(input.url, {waitUntil: 'domcontentloaded'});
    if (!response?.ok()) throw new Error('Page retrieval returned HTTP ' + response?.status());
    const text = await page.locator('body').innerText();
    console.log(JSON.stringify({url: page.url(), title: await page.title(), text: text.slice(0, 60000)}));
  } else throw new Error('Unknown action');
} catch (error) {
  console.log(JSON.stringify({error: error.message}));
  process.exitCode = 1;
} finally { await browser.close(); }
