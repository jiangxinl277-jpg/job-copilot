#!/usr/bin/env node
/**
 * Second-level probe: click into a detail view and print what appears.
 * Usage: node scripts/probe_click.js <mode> <url>
 *   mode = click-detail   -> click first link whose text is 详情, dump body
 *   mode = read-body      -> just dump body text (for iframe urls)
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const [mode, url] = process.argv.slice(2);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const port = 9800 + Math.floor(Math.random() * 150);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'probe2-'));
  const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu',
    '--remote-debugging-port=' + port, '--user-data-dir=' + profile, 'about:blank'],
    { stdio: 'ignore' });
  let ok = false;
  for (let i = 0; i < 60 && !ok; i++) {
    try { ok = (await fetch(`http://127.0.0.1:${port}/json/version`)).ok; } catch (e) { await wait(500); }
  }
  const tab = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`,
    { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  const pending = new Map(); let seq = 0;
  const send = (m, p = {}) => new Promise((res) => {
    const id = ++seq; pending.set(id, res); ws.send(JSON.stringify({ id, method: m, params: p }));
  });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
  };
  await new Promise((r) => (ws.onopen = r));
  await send('Page.enable'); await send('Runtime.enable');
  await wait(11000);

  if (mode === 'click-detail') {
    const clicked = await send('Runtime.evaluate', {
      expression: `(() => {
        const a = [...document.querySelectorAll('a,button,span,div')]
          .find(e => (e.innerText||'').trim() === '详情' && e.offsetParent);
        if (!a) return 'none';
        a.click();
        return 'clicked';
      })()`, returnByValue: true });
    console.log('click:', clicked.result.value);
    await wait(4000);
  }

  const r = await send('Runtime.evaluate', {
    expression: `JSON.stringify({
      title: document.title,
      textLen: (document.body.innerText||'').length,
      text: (document.body.innerText||'').slice(0, 2500),
      modals: [...document.querySelectorAll('[class*=modal],[class*=dialog],[class*=drawer],[class*=popup],[class*=detail]')]
        .filter(e => e.offsetParent).slice(0,6).map(e => ({cls:String(e.className).slice(0,60), len:(e.innerText||'').length}))
    })`, returnByValue: true });
  const out = JSON.parse(r.result.value);
  console.log(JSON.stringify({ mode, url, title: out.title, textLen: out.textLen, modals: out.modals }, null, 1));
  console.log('--- TEXT ---');
  console.log(out.text);
  chrome.kill(); process.exit(0);
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
