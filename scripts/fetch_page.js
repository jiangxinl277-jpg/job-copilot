#!/usr/bin/env node
/**
 * Dependency-free headless page fetcher (Chrome DevTools Protocol).
 *
 * Usage:
 *   node scripts/fetch_page.js --out data/raw --wait 8000 <url> [url...]
 *
 * For each URL it opens a fresh tab, waits for load + an extra settle window,
 * scrolls to the bottom twice (to trigger lazy rendering), then saves:
 *   <out>/<slug>.txt      visible text (innerText) of the page
 *   <out>/<slug>.json     { url, finalUrl, title, chars, fetchedAt }
 *
 * Why not Playwright: this machine's bundled playwright package is incomplete;
 * CDP via a local Chrome install needs no extra dependencies.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
].filter(Boolean);

const args = process.argv.slice(2);
const outIdx = args.indexOf('--out');
const waitIdx = args.indexOf('--wait');
const uaIdx = args.indexOf('--ua');
const outDir = outIdx >= 0 ? args[outIdx + 1] : 'data/raw';
const settleMs = waitIdx >= 0 ? Number(args[waitIdx + 1]) : 8000;
const userAgent = uaIdx >= 0 ? args[uaIdx + 1] : '';
const urls = args.filter(
  (a, i) =>
    a.startsWith('http') &&
    !(outIdx >= 0 && i === outIdx + 1) &&
    !(waitIdx >= 0 && i === waitIdx + 1) &&
    !(uaIdx >= 0 && i === uaIdx + 1)
);

if (!urls.length) {
  console.error('no urls given');
  process.exit(2);
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const slugOf = (u, i) =>
  (new URL(u).hostname + '-' + (new URL(u).pathname.replace(/[^a-z0-9]+/gi, '-').slice(0, 40)))
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'page-' + i;

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const chromePath = CHROME_CANDIDATES.find((p) => fs.existsSync(p));
  if (!chromePath) throw new Error('Chrome not found');

  const port = 9400 + Math.floor(Math.random() * 200);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-'));
  const chrome = spawn(
    chromePath,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      '--remote-debugging-port=' + port,
      '--user-data-dir=' + profile,
      'about:blank',
    ],
    { stdio: 'ignore' }
  );

  let ready = false;
  for (let i = 0; i < 60 && !ready; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      ready = r.ok;
    } catch (e) {
      await wait(500);
    }
  }
  if (!ready) throw new Error('devtools not ready');

  const results = [];
  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    const slug = slugOf(url, i);
    let tab;
    try {
      tab = await (
        await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, {
          method: 'PUT',
        })
      ).json();
    } catch (e) {
      results.push({ url, ok: false, error: 'tab open failed' });
      continue;
    }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    const pending = new Map();
    let seq = 0;
    const send = (method, params = {}) =>
      new Promise((resolve) => {
        const id = ++seq;
        pending.set(id, resolve);
        ws.send(JSON.stringify({ id, method, params }));
      });
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg.result);
        pending.delete(msg.id);
      }
    };
    await new Promise((r) => (ws.onopen = r));
    await send('Page.enable');
    await send('Runtime.enable');
    if (userAgent) {
      await send('Network.enable');
      await send('Network.setUserAgentOverride', { userAgent });
    }
    await send('Page.navigate', { url });
    await wait(settleMs);

    // scroll twice to trigger lazy rendering
    for (let s = 0; s < 2; s++) {
      await send('Runtime.evaluate', {
        expression: 'window.scrollTo(0, document.body.scrollHeight)',
      });
      await wait(1500);
    }
    const meta = await send('Runtime.evaluate', {
      expression:
        'JSON.stringify({title: document.title, url: location.href, text: document.body ? document.body.innerText : ""})',
      returnByValue: true,
    });
    let parsed = { title: '', url, text: '' };
    try {
      parsed = JSON.parse(meta.result.value);
    } catch (e) {}
    const text = (parsed.text || '').replace(/\n{3,}/g, '\n\n').trim();
    fs.writeFileSync(path.join(outDir, slug + '.txt'), text, 'utf8');
    fs.writeFileSync(
      path.join(outDir, slug + '.json'),
      JSON.stringify(
        { url, finalUrl: parsed.url, title: parsed.title, chars: text.length, fetchedAt: new Date().toISOString() },
        null,
        1
      )
    );
    results.push({ url, slug, title: parsed.title, chars: text.length });
    ws.close();
    await fetch(`http://127.0.0.1:${port}/json/close/${tab.id}`).catch(() => {});
    await wait(500);
  }

  console.log(JSON.stringify(results, null, 1));
  chrome.kill();
  process.exit(0);
}

main().catch((e) => {
  console.error('ERR', e.message);
  process.exit(1);
});
