#!/usr/bin/env node
/**
 * Capture the README UI previews from the isolated local demonstration runtime.
 *
 * Prerequisites:
 *   1. Run scripts/seed_readme_demo.py.
 *   2. Start the backend with BILI_DATA_DIR=tmp/readme-screenshots-data and
 *      BILI_AUTH_PATH pointing to its readme-demo-auth.json file.
 *   3. Start the frontend on http://127.0.0.1:5174 and Chrome with
 *      --remote-debugging-port=9333.
 *
 * The script uses only synthetic local data and writes generated PNG assets to
 * docs/images. It never calls Bilibili or an LLM service.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const BASE_URL = process.env.README_DEMO_URL || 'http://127.0.0.1:5174/#/';
const DEBUG_PORT = Number(process.env.README_SCREENSHOT_DEBUG_PORT || 9333);
const OUTPUT_DIR = resolve('docs/images');

const delay = (ms) => new Promise((resolveDelay) => setTimeout(resolveDelay, ms));

async function newTarget(url) {
  const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
  if (!response.ok) throw new Error(`无法创建用于截图的 Chrome 页面：${response.status}`);
  return response.json();
}

function connect(webSocketDebuggerUrl) {
  const socket = new WebSocket(webSocketDebuggerUrl);
  const pending = new Map();
  let sequence = 0;
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  return new Promise((resolveConnection, rejectConnection) => {
    socket.addEventListener('open', () => resolveConnection({
      send(method, params = {}) {
        const id = ++sequence;
        socket.send(JSON.stringify({ id, method, params }));
        return new Promise((resolveRequest, rejectRequest) => pending.set(id, { resolve: resolveRequest, reject: rejectRequest }));
      },
      close() { socket.close(); },
    }), { once: true });
    socket.addEventListener('error', () => rejectConnection(new Error('无法连接 Chrome DevTools。')), { once: true });
  });
}

async function evaluate(cdp, expression) {
  const result = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || '页面脚本执行失败');
  return result.result.value;
}

async function waitFor(cdp, expression, description) {
  const until = Date.now() + 12_000;
  while (Date.now() < until) {
    if (await evaluate(cdp, expression)) return;
    await delay(150);
  }
  throw new Error(`等待界面超时：${description}`);
}

async function screenshot(cdp, filename) {
  await delay(350);
  const capture = await cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false });
  writeFileSync(resolve(OUTPUT_DIR, filename), Buffer.from(capture.data, 'base64'));
}

async function openHome(cdp) {
  await cdp.send('Page.navigate', { url: BASE_URL });
  await waitFor(cdp, "document.body.innerText.includes('历史记录')", '历史记录加载');
  await delay(350);
}

async function selectVideo(cdp) {
  await evaluate(cdp, `(() => {
    const record = document.querySelector('.history-panel__list .history-panel__record');
    if (!record) return false;
    record.click();
    return true;
  })()`);
  await waitFor(cdp, "document.body.innerText.includes('情感') && document.body.innerText.includes('示例：社区讨论热度观察')", '单视频分析结果');
}

async function selectEvent(cdp) {
  await evaluate(cdp, `(() => {
    const tab = [...document.querySelectorAll('[role=tab]')].find((element) => element.textContent.trim() === '舆情事件');
    if (!tab) return false;
    tab.click();
    return true;
  })()`);
  await waitFor(cdp, "document.body.innerText.includes('示例事件：多视频讨论对比（脱敏）')", '事件历史加载');
  await evaluate(cdp, `(() => {
    const record = document.querySelector('.history-panel__record--group');
    if (!record) return false;
    record.click();
    return true;
  })()`);
  await waitFor(cdp, "document.body.innerText.includes('舆情事件 ·')", '事件工作台加载');
}

async function main() {
  mkdirSync(OUTPUT_DIR, { recursive: true });
  const target = await newTarget(BASE_URL);
  const cdp = await connect(target.webSocketDebuggerUrl);
  try {
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1440, height: 1024, deviceScaleFactor: 1, mobile: false,
    });

    await openHome(cdp);
    await screenshot(cdp, 'demo-history.png');

    await selectVideo(cdp);
    await screenshot(cdp, 'demo-analysis-overview.png');

    await evaluate(cdp, "document.querySelector('.distribution-chart-card')?.scrollIntoView({ block: 'center' })");
    await waitFor(cdp, "document.body.innerText.includes('情感分布') && document.body.innerText.includes('导出图片')", '情感分布图表');
    await screenshot(cdp, 'demo-analysis-charts.png');

    await evaluate(cdp, `(() => {
      const tab = [...document.querySelectorAll('[role=tab]')].find((element) => element.textContent.trim() === '弹幕时间轴');
      if (!tab) return false;
      tab.click();
      return true;
    })()`);
    await waitFor(cdp, "document.body.innerText.includes('弹幕') && document.body.innerText.includes('已完成')", '弹幕时间轴');
    await screenshot(cdp, 'demo-danmaku-timeline.png');

    await selectEvent(cdp);
    await screenshot(cdp, 'demo-event-workspace.png');
  } finally {
    cdp.close();
  }
}

main().then(() => console.log(`README 截图已写入 ${OUTPUT_DIR}`)).catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
