#!/usr/bin/env node
/**
 * Adapter: Beisen "hotjob" portals (e.g. gzcb.hotjob.cn).
 *
 * Reality check (probed 2026-10-22): the portal page is an empty shell; the
 * content lives in an iframe (/SU.../pb/index.html). The iframe shows the
 * position list (总行管培生/分行管培生/...) without login.
 *
 * Strategy:
 *   1) open portal -> read iframe src -> open the iframe document;
 *   2) harvest position names from the list;
 *   3) click each position and capture whatever text appears;
 *   4) if a click lands on a login page, record needs_login for that position.
 *
 * Usage: node adapters/hotjob.js --url https://gzcb.hotjob.cn/ --out data/raw/hotjob
 */
const fs = require('fs');
const path = require('path');
const { withPage } = require('../lib/cdp');

const arg = (name, def) => {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : def;
};
const PORTAL = arg('--url', 'https://gzcb.hotjob.cn/');
const OUT = arg('--out', 'data/raw/hotjob');
const MAX_JOBS = Number(arg('--max', '5'));

const clean = (s) => (s || '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
const isLogin = (text, title) => /登录|注册/.test(title + text) && text.length < 400;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  // 1) find the iframe
  const iframeSrc = await withPage(PORTAL, async (p) => {
    const frames = await p.frames();
    return frames.find((f) => /\/pb\/index\.html/.test(f)) || frames[0] || '';
  }, { settle: 12000 });
  if (!iframeSrc) throw new Error('iframe not found');

  // 2) read the iframe document
  const list = await withPage(iframeSrc, async (p) => {
    const body = clean(await p.bodyText());
    const names = body.split('\n').map((s) => s.trim())
      .filter((s) => s && !/关于我们|岗位投递|登录|注册|公网安备|ICP备/.test(s))
      .slice(0, 20);
    return { title: await p.title(), body, names };
  }, { settle: 11000 });

  fs.writeFileSync(path.join(OUT, 'list.txt'), list.body, 'utf8');
  const jobs = list.names.slice(0, MAX_JOBS);
  const results = [];

  // 3) click each position, capture the detail panel
  for (const job of jobs) {
    const detail = await withPage(iframeSrc, async (p) => {
      const clicked = await p.eval(`(() => {
        const t = ${JSON.stringify(job)};
        const el = [...document.querySelectorAll('div,span,a,li')]
          .find(e => (e.innerText||'').trim() === t && e.offsetParent);
        if (!el) return 'none';
        el.click();
        return 'clicked';
      })()`);
      await p.sleep(4000);
      const title = await p.title();
      const url = await p.url();
      const text = clean(await p.bodyText());
      return { clicked, title, url, text };
    }, { settle: 10000 });

    // 点击后文本没有超出列表页太多 => 详情没渲染出来（登录墙或需要选卡片）
    const unchanged = detail.text.length <= list.body.length + 40;
    const status = isLogin(detail.text, detail.title)
      ? 'needs_login'
      : unchanged
        ? 'needs_login_or_paste'
        : detail.text.length > 400 ? 'ok' : 'thin';
    const slug = job.replace(/[^\w\u4e00-\u9fa5]+/g, '_').slice(0, 30);
    fs.writeFileSync(path.join(OUT, slug + '.txt'), detail.text, 'utf8');
    results.push({
      job,
      status,
      clicked: detail.clicked,
      title: detail.title,
      url: detail.url,
      chars: detail.text.length,
      file: slug + '.txt',
    });
  }

  const summary = {
    adapter: 'hotjob',
    portal: PORTAL,
    iframe: iframeSrc,
    list_title: list.title,
    positions: list.names,
    fetched: results,
    fetched_at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(OUT, 'summary.json'), JSON.stringify(summary, null, 1), 'utf8');
  console.log(JSON.stringify(summary, null, 1));
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
