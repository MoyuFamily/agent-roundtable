"""Offline browser checks using synthetic reports from the real Python renderer."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from roundtable.evidence import render_report

ROOT = Path(__file__).resolve().parents[1]


def synthetic_snapshot():
    recommendation = (
        '开展 7 天试点，预算 1.25 人天。成本 < 2.5 & "time" > 0.5。\n第二行：[Plan_A] (trial) *literal* #tag!'
    )
    statement = "合成样本的处理时间为 1.25 秒，上限 10.5 秒。\n第二行：保留边界 <sample> & 证据尾部 END_OF_EVIDENCE。"
    evidence = {
        "sources": [
            {
                "id": "S1",
                "title": "合成容量记录 / Synthetic capacity notes",
                "reference": "synthetic:S1?version=1.25&scope=trial",
                "version": "1.25",
                "date": "2026-11-17",
            }
        ],
        "items": [
            {
                "id": "F1",
                "kind": "fact",
                "verification": "verified",
                "statement": statement,
                "citations": [{"source_id": "S1", "locator": "第 2 页，第 1.25 节"}],
                "applicability": "仅用于本地合成报告验收",
            }
        ],
    }
    report = {
        "status": "proposed",
        "recommendation": recommendation,
        "rationale": [{"text": "先验证可交付性，再决定是否扩大投入。", "evidence_ids": ["F1"]}],
        "tradeoffs": ["投入 1.25 人天；暂停一项低优先级任务。"],
        "uncertainties": ["尚未验证真实需求、留存与支持成本。"],
        "revisit_conditions": ["若试点成本超过 2.5 人天，则重新评估范围。"],
        "next_actions": ["记录成功标准与负责人。\n7 天后复核，保留未解决问题。"],
    }
    conclusion = render_report(report, evidence, 1)
    return {
        "snapshot": {
            "topic": "试点范围决策 · 合成报告",
            "status": "concluded",
            "conclusion": conclusion,
            "participants": [{"profile": "a", "display_name": "Analyst", "role": "Research"}],
            "speeches": [{"id": 1, "round": 1, "participant": "a", "content": "Synthetic process notes."}],
            "round_summaries": [{"round": 1, "consensus": ["Recorded note"], "disagreement": []}],
            "final_summary": {
                "verdict": "STALE_VERDICT",
                "consensus": ["Process consensus"],
                "disagreement": ["Unresolved process question"],
            },
        },
        "literals": recommendation.splitlines() + statement.splitlines(),
    }


# Every request is fulfilled locally or rejected. CDN scripts are replaced with
# installed marked, the viewer's sanitizer fallback, and the small Tailwind utility
# subset used by these templates. No browser profile or external material is read.
BROWSER_RUNNER = r"""
import assert from 'node:assert/strict';
import {readFileSync, existsSync, mkdirSync} from 'node:fs';
import {join, dirname} from 'node:path';
import {createRequire} from 'node:module';
const input = JSON.parse(readFileSync(0, 'utf8'));
const require = createRequire(join(process.cwd(), 'package.json'));
let puppeteer, markedPath;
try {
  const rendererRequire = createRequire(require.resolve('md-to-pdf'));
  puppeteer = rendererRequire('puppeteer');
  markedPath = join(dirname(rendererRequire.resolve('marked')), 'marked.umd.js');
} catch (error) {
  console.error('Browser test dependencies unavailable: ' + error.message);
  process.exit(77);
}
const chrome = process.env.PUPPETEER_EXECUTABLE_PATH ||
  (process.platform === 'darwin'
    ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : puppeteer.executablePath());
if (!existsSync(chrome)) { console.error('Chrome unavailable: ' + chrome); process.exit(77); }
const web = join(process.cwd(), 'src/roundtable/web');
const utilityCSS = '.hidden{display:none!important}.flex{display:flex}.flex-col{flex-direction:column}' +
  '.flex-1{flex:1 1 0%}.items-center{align-items:center}.items-start{align-items:flex-start}' +
  '.justify-between{justify-content:space-between}.justify-center{justify-content:center}' +
  '.gap-2{gap:8px}.gap-3{gap:12px}.min-w-0{min-width:0}.relative{position:relative}' +
  '.mb-2{margin-bottom:8px}.mb-3{margin-bottom:12px}.mb-4{margin-bottom:16px}' +
  '.pb-2{padding-bottom:8px}.py-3{padding-top:12px;padding-bottom:12px}.py-4{padding-top:16px;padding-bottom:16px}' +
  '.font-semibold{font-weight:600}.font-medium{font-weight:500}.text-lg{font-size:18px;line-height:28px}' +
  '.text-base{font-size:16px;line-height:24px}.text-sm{font-size:14px;line-height:20px}' +
  '.text-xs{font-size:12px;line-height:16px}.leading-relaxed{line-height:1.625}' +
  '.overflow-x-auto{overflow-x:auto}.ml-auto{margin-left:auto}';
const browser = await puppeteer.launch({executablePath: chrome, headless: true, pipe: true,
  args: process.env.ROUNDTABLE_PDF_NO_SANDBOX === '1' ? ['--no-sandbox'] : []});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewport({width:1280, height:900});
  await page.emulateMediaFeatures([{name:'prefers-reduced-motion', value:'reduce'}]);
  await page.setRequestInterception(true);
  page.on('request', request => {
    const url = new URL(request.url());
    const respond = (body, contentType) => request.respond({status:200, contentType, body});
    if (url.hostname === 'cdn.tailwindcss.com') {
      return respond('const s=document.createElement("style");s.textContent=' +
        JSON.stringify(utilityCSS) + ';document.head.appendChild(s);', 'application/javascript');
    }
    if (url.hostname === 'cdn.jsdelivr.net' && url.pathname.includes('/marked/')) {
      return respond(readFileSync(markedPath), 'application/javascript');
    }
    if (url.hostname === 'cdn.jsdelivr.net' && url.pathname.includes('/dompurify')) {
      return respond('', 'application/javascript');
    }
    if (url.hostname !== 'roundtable.test') return request.abort();
    if (url.pathname === '/r/synthetic') {
      return respond(readFileSync(join(web, input.template)), 'text/html');
    }
    if (url.pathname.endsWith('/replay/meta')) {
      return respond(JSON.stringify({ok:true, duration:1000, rounds:[], agents:[]}), 'application/json');
    }
    if (['/viewer.js','/i18n.js','/theme.css','/viewer.css'].includes(url.pathname)) {
      return respond(readFileSync(join(web, url.pathname.slice(1))),
        url.pathname.endsWith('.css') ? 'text/css' : 'application/javascript');
    }
    return request.abort();
  });
  await page.evaluateOnNewDocument(embed => {
    localStorage.setItem('rt_lang', 'zh-CN');
    window.__RT_CONFIG__ = {token:'synthetic', embed};
    window.__streams = [];
    window.EventSource = class {
      constructor(url) { this.url = url; this.listeners = {}; window.__streams.push(this); }
      addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
      emit(name, data) { for (const fn of this.listeners[name] || []) fn({data:JSON.stringify(data)}); }
      close() {}
    };
  }, input.template === 'embed.html');
  await page.goto('http://roundtable.test/r/synthetic', {waitUntil:'load'});
  const send = data => page.evaluate(data => window.__streams[0].emit('update', data), data);
  const inspect = () => page.evaluate(() => ({
    text: document.getElementById('conclusionContent').textContent,
    processOpen: document.getElementById('discussionProcess').open,
    reportVisible: !document.getElementById('conclusionCard').classList.contains('hidden'),
    activeVisible: !document.getElementById('activeState').classList.contains('hidden'),
    waitingHidden: document.getElementById('waitingState').classList.contains('hidden'),
    scroll: window.scrollY,
  }));
  await send(input.snapshot);
  let view = await inspect();
  assert.equal(view.processOpen, false);
  assert(view.reportVisible && view.activeVisible && view.waitingHidden);
  assert(!view.text.includes('STALE_VERDICT'));
  for (const literal of input.literals) assert(view.text.includes(literal), literal + '\n' + view.text);
  for (const escaped of ['1\\.25', '&lt;', '&amp;', '\\[']) assert(!view.text.includes(escaped), escaped);
  assert.equal(view.scroll, 0);
  const structure = await page.evaluate(() => {
    const card = document.getElementById('conclusionCard');
    return {h1:card.querySelectorAll('h1').length, h2:card.querySelectorAll('.markdown-content h2').length,
      h3:card.querySelectorAll('h3').length, breaks:card.querySelectorAll('br').length,
      sampleElements:card.querySelectorAll('sample,script,iframe').length,
      first:document.getElementById('activeState').firstElementChild.id};
  });
  assert.equal(structure.first, 'conclusionCard');
  assert(structure.h1 === 1 && structure.h2 >= 8 && structure.h3 >= 2 && structure.breaks >= 2);
  assert.equal(structure.sampleElements, 0);

  if (input.template === 'index.html' && process.env.ROUNDTABLE_VIEWER_SCREENSHOT_DIR) {
    const directory = process.env.ROUNDTABLE_VIEWER_SCREENSHOT_DIR;
    mkdirSync(directory, {recursive:true});
    await page.screenshot({path:join(directory, 'desktop.png')});
    // Width-only emulation avoids a page reload that would reset the synthetic SSE.
    await page.setViewport({width:390, height:844, deviceScaleFactor:1});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Mobile overflow');
    await page.screenshot({path:join(directory, 'mobile.png')});
    await page.evaluate(() => {
      const heading = [...document.querySelectorAll('#conclusionContent h2')]
        .find(el => el.textContent === '被引用证据');
      window.scrollTo(0, heading.getBoundingClientRect().top + window.scrollY - 100);
    });
    await page.screenshot({path:join(directory, 'mobile-evidence.png')});
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.setViewport({width:1280, height:900});
  }

  // Report revisions update in place without closing the user's expanded process
  // or moving the scroll position; duplicate snapshots preserve the report DOM.
  await page.evaluate(() => { document.getElementById('discussionProcess').open = true; window.scrollTo(0, 200); });
  const updated = {...input.snapshot, conclusion:input.snapshot.conclusion + '\n\nUPDATED_REPORT_END'};
  await send(updated);
  view = await inspect();
  assert(view.text.includes('UPDATED_REPORT_END'));
  assert.equal(view.processOpen, true);
  assert.equal(view.scroll, 200);
  await page.evaluate(() => { window.__reportNode = document.getElementById('conclusionContent').firstChild; });
  await send(updated);
  assert(await page.evaluate(() => window.__reportNode === document.getElementById('conclusionContent').firstChild));
  await page.evaluate(() => window.__streams[0].emit('delta', {events:[
    {type:'status_delta', status:'concluded', conclusion:'OLD_DELTA'},
    {type:'final_summary', verdict:'STALE_VERDICT', consensus:['Late process note']},
  ]}));
  assert((await inspect()).text.includes('UPDATED_REPORT_END'));
  assert(!(await inspect()).text.includes('OLD_DELTA'));

  if (input.template === 'index.html') {
    // Use the actual replay listener, not a replacement rendering implementation.
    await page.evaluate(() => { enterReplayMode(); startReplayStream(0); });
    await page.evaluate(() => {
      const replay = window.__streams.at(-1);
      replay.emit('replay_event', {type:'status_delta', status:'active', conclusion:'HISTORICAL_REPORT'});
      replay.emit('replay_event', {type:'final_summary', verdict:'HISTORICAL_VERDICT', consensus:['Historical note']});
    });
    assert((await inspect()).text.includes('UPDATED_REPORT_END'));
    await send({...updated, conclusion:updated.conclusion + '\n\nLIVE_DURING_REPLAY'});
    await page.evaluate(() => exitReplayMode());
    assert((await inspect()).text.includes('LIVE_DURING_REPLAY'));
    assert.equal(await page.$eval('#statusLabel', el => el.textContent), '已结束');
  }

  // A concluded discussion can have no report or speeches. Legacy verdicts do not
  // become a second truth, and the empty state changes language with the chrome.
  await page.reload({waitUntil:'load'});
  await send({...input.snapshot, status:'active', conclusion:null, speeches:[], round_summaries:[]});
  view = await inspect();
  assert(view.processOpen && !view.reportVisible);
  await send({...input.snapshot, conclusion:null, speeches:[], round_summaries:[]});
  view = await inspect();
  assert(view.text.includes('讨论已结束，尚未提交结论。'));
  assert(view.processOpen && view.reportVisible && view.activeVisible);
  if (input.template === 'index.html') {
    await page.click('#langSwitchBtn');
    assert((await inspect()).text.includes('Discussion ended; no conclusion has been submitted.'));
    assert.equal(await page.$eval('#discussionProcess > summary', el => el.textContent), 'Discussion process');
  }
  assert.deepEqual(errors, []);
  await send({...input.snapshot, speeches:[], round_summaries:[]});
  view = await inspect();
  assert(view.reportVisible && view.activeVisible && !view.processOpen);
  console.log('PASS ' + input.template + ': literal report, updates, process defaults, scrolling, replay, empty state');
} finally {
  await browser.close();
}
"""


@pytest.mark.parametrize("template", ["index.html", "embed.html"])
def test_canonical_report_browser_behavior(template):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", BROWSER_RUNNER],
        input=json.dumps({**synthetic_snapshot(), "template": template}, ensure_ascii=False),
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    if result.returncode == 77:
        if os.environ.get("ROUNDTABLE_REQUIRE_PDF") == "1":
            pytest.fail(result.stderr)
        pytest.skip(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
