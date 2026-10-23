#!/usr/bin/env node
/**
 * Probe a page's DOM to design a site adapter.
 * Prints frames, "详情"-like clickables, canvas/shadow usage, and body size.
 *
 * Usage: node scripts/probe_page.js <url> [--wait 9000]
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const args = process.argv.slice(2);
const url = args.find((a) => a.startsWith('http'));
const wi = args.indexOf('--wait');
const settle = wi >= 0 ? Number(args[wi + 1]) : 9000;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const port = 9600 + Math.floor(Math.random() * 200);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'probe-'));
  const chrome = spawn(
    CHROME,
    ['--headless=new', '--disable-gpu', '--remote-debugging-port=' + port,
     '--user-data-dir=' + profile, 'about:blank'],
    { stdio: 'ignore' }
  );
  let ok = false;
  for (let i = 0; i < 60 && !ok; i++) {
    try { ok = (await fetch(`http://127.0.0.1:${port}/json/version`)).ok; }
    catch (e) { await wait(500); }
  }
  const tab = await (await fetch(
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`,
    { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  const pending = new Map();
  let seq = 0;
  const send = (m, p = {}) => new Promise((res) => {
    const id = ++seq; pending.set(id, res); ws.send(JSON.stringify({ id, method: m, params: p }));
  });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
  };
  await new Promise((r) => (ws.onopen = r));
  await send('Page.enable');
  await send('Runtime.enable');
  await wait(settle);

  const expr = `(() => {
    const txt = (e) => (e.innerText || e.textContent || '').trim();
    const det = [...document.querySelectorAll('a,button,span,div,li')]
      .filter(e => /^详情|查看详情|立即申请|投递$/.test(txt(e)) && e.offsetParent)
      .slice(0, 12)
      .map(e => ({ tag: e.tagName, cls: String(e.className).slice(0, 60), text: txt(e).slice(0, 20), href: e.href || '' }));
    return JSON.stringify({
      title: document.title,
      textLen: (document.body.innerText || '').length,
      htmlLen: document.documentElement.outerHTML.length,
      frames: [...document.querySelectorAll('iframe')].map(f => ({ src: f.src, w: f.clientWidth, h: f.clientHeight })),
      canvas: document.querySelectorAll('canvas').length,
      shadowHosts: [...document.querySelectorAll('*')].filter(e => e.shadowRoot).length,
      details: det,
      bodyHead: (document.body.innerText || '').slice(0, 300)
    });
  })()`;
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
  console.log(r.result.value);
  chrome.kill();
  process.exit(0);
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
