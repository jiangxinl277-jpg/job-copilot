#!/usr/bin/env node
/**
 * Adapter: CITIC Securities campus portal (careers.citics.com).
 *
 * Reality check (probed 2026-10-22): the list page renders job names plus a
 * "详情" link; clicking it redirects to the 手机号登录 page. So this adapter
 * cannot fetch JD text anonymously. It does two useful things instead:
 *   1) harvest the public job-name list (what the list page shows);
 *   2) detect the login wall and return status=needs_login, so the pipeline
 *      falls back to the announcement link / manual paste instead of writing
 *      an empty JD.
 *
 * Usage: node adapters/citic.js --out data/raw/citic
 */
const fs = require('fs');
const path = require('path');
const { withPage } = require('../lib/cdp');

const URL = process.argv.includes('--url')
  ? process.argv[process.argv.indexOf('--url') + 1]
  : 'https://careers.citics.com/campus/headquarters';
const outDir = process.argv.includes('--out')
  ? process.argv[process.argv.indexOf('--out') + 1]
  : 'data/raw/citic';

const isLogin = (text, title) =>
  /登录|手机号登录|立即登录/.test(title + '\n' + text) && text.length < 600;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });

  // 1) list page: job names + 详情 links
  const listed = await withPage(URL, async (p) => {
    const data = await p.eval(`JSON.stringify({
      title: document.title,
      body: document.body.innerText,
      details: [...document.querySelectorAll('a,button')]
        .filter(e => (e.innerText||'').trim() === '详情')
        .map(e => ({ text: e.innerText.trim(), href: e.href || '' })),
      cards: [...document.querySelectorAll('li,div')]
        .filter(e => e.offsetParent && (e.innerText||'').length > 4 && (e.innerText||'').length < 40)
        .slice(0, 60)
        .map(e => (e.innerText||'').replace(/\\s+/g, ' ').trim())
    })`);
    return JSON.parse(data);
  });

  fs.writeFileSync(path.join(outDir, 'list.txt'), listed.body, 'utf8');
  const jobs = listed.details.map((d, i) => listed.cards.find((c) => false) || `岗位 ${i + 1}`);

  // 2) click the first 详情 to confirm the login wall
  const detail = await withPage(URL, async (p) => {
    const clicked = await p.eval(`(() => {
      const a = [...document.querySelectorAll('a,button')]
        .find(e => (e.innerText||'').trim() === '详情' && e.offsetParent);
      if (!a) return 'none';
      a.click();
      return 'clicked';
    })()`);
    await p.sleep(4000);
    const title = await p.title();
    const url = await p.url();
    const text = await p.bodyText();
    return { clicked, title, url, text };
  });

  const loginWall = isLogin(detail.text || '', detail.title || '');
  const status = loginWall ? 'needs_login' : (detail.text || '').length > 500 ? 'ok' : 'needs_paste';
  fs.writeFileSync(path.join(outDir, 'detail_attempt.txt'), detail.text || '', 'utf8');

  const summary = {
    adapter: 'citic',
    source: URL,
    status,
    reason: loginWall
      ? '点击“详情”后跳转手机号登录页，JD 需要登录后可见'
      : '详情页可读取',
    list_title: listed.title,
    detail_count: listed.details.length,
    job_names: listed.body
      .split('\n')
      .map((s) => s.trim())
      .filter((s) => s && !/详情|登录|中信证券|人才招聘|校园招聘|社会招聘|实习生|我的申请|客服|关于|版权|京ICP|公安|风险/.test(s))
      .slice(0, 30),
    fetched_at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 1), 'utf8');
  console.log(JSON.stringify(summary, null, 1));
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
