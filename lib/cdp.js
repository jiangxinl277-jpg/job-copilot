// Minimal Chrome DevTools Protocol helper (no npm dependencies).
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
].filter(Boolean);

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function withPage(url, fn, { settle = 9000 } = {}) {
  const chromePath = CHROME_CANDIDATES.find((p) => fs.existsSync(p));
  if (!chromePath) throw new Error('Chrome not found');
  const port = 9200 + Math.floor(Math.random() * 400);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-'));
  const chrome = spawn(chromePath, [
    '--headless=new', '--disable-gpu', '--no-first-run',
    '--remote-debugging-port=' + port, '--user-data-dir=' + profile, 'about:blank',
  ], { stdio: 'ignore' });

  try {
    let ready = false;
    for (let i = 0; i < 60 && !ready; i++) {
      try { ready = (await fetch(`http://127.0.0.1:${port}/json/version`)).ok; }
      catch (e) { await wait(500); }
    }
    if (!ready) throw new Error('devtools not ready');

    const tab = await (await fetch(
      `http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`,
      { method: 'PUT' })).json();
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    const pending = new Map();
    let seq = 0;
    const send = (method, params = {}) => new Promise((res) => {
      const id = ++seq;
      pending.set(id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
    };
    await new Promise((r) => (ws.onopen = r));
    await send('Page.enable');
    await send('Runtime.enable');
    await wait(settle);

    const api = {
      eval: async (expression) => {
        const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
        return r && r.result ? r.result.value : undefined;
      },
      bodyText: async () => api.eval('document.body ? document.body.innerText : ""'),
      title: async () => api.eval('document.title'),
      url: async () => api.eval('location.href'),
      frames: async () => api.eval(
        'JSON.stringify([...document.querySelectorAll("iframe")].map(f=>f.src))'
      ).then((s) => JSON.parse(s || '[]')),
      sleep: wait,
    };
    return await fn(api);
  } finally {
    chrome.kill();
  }
}

module.exports = { withPage, wait };
