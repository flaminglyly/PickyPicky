import {safeUrl, mediaKind, filename, pageInfo} from './core.mjs';
let pending = Promise.resolve();
function transaction(fn) {
  const result = pending.then(fn);
  pending = result.catch(() => {});
  return result;
}
async function getState() { return (await chrome.storage.session.get('watch')).watch; }
async function record(state, url, mime = '', size = '', metadata = {}) {
  url = safeUrl(url);
  if (!url) return;
  const kind = mediaKind(url, mime);
  if (!kind || kind === 'segment') return;
  const existing = state.items.find(i => i.url === url);
  if (existing) { existing.mime = mime || existing.mime; existing.size = size || existing.size; Object.assign(existing, metadata); }
  else state.items.push({id: crypto.randomUUID(), url, kind, mime, size, ...metadata, time: Date.now()});
  state.items = state.items.slice(-200);
  await chrome.storage.session.set({watch: state});
}
chrome.webRequest.onHeadersReceived.addListener(details => {
  transaction(async () => {
    const state = await getState();
    if (!state || state.tabId !== details.tabId || details.statusCode >= 400) return;
    const header = name => details.responseHeaders?.find(h => h.name.toLowerCase() === name)?.value || '';
    await record(state, details.url, header('content-type'), header('content-length'));
  }).catch(console.error);
}, {urls: ['http://*/*', 'https://*/*']}, ['responseHeaders']);
chrome.tabs.onRemoved.addListener(tabId => transaction(async () => {
  if ((await getState())?.tabId === tabId) await chrome.storage.session.remove('watch');
}).catch(console.error));
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id) return;
  transaction(async () => {
    if (message.type === 'start') {
      const tab = await chrome.tabs.get(message.tabId);
      if (!safeUrl(tab.url)) throw new Error('请先打开普通网页。');
      await chrome.storage.session.set({watch: {tabId: tab.id, pageUrl: tab.url, title: String(message.title || pageInfo(tab.url, tab.title).title || ''), preview: pageInfo(tab.url).preview, items: []}});
      return {};
    }
    if (message.type === 'state') return {watch: await getState()};
    if (message.type === 'stop') { await chrome.storage.session.remove('watch'); return {}; }
    const state = await getState();
    if (!state) throw new Error('请先启用页面检测。');
    if (message.type === 'scan') {
      const results = await chrome.scripting.executeScript({target: {tabId: state.tabId}, func: () => ({
        pageUrl: location.href,
        videos: [...document.querySelectorAll('video')].flatMap(v => [v.currentSrc, v.src, ...[...v.querySelectorAll('source')].map(s => s.src)].filter(Boolean).map(url => ({url, duration: Number.isFinite(v.duration) ? v.duration : null}))),
        resources: performance.getEntriesByType('resource').map(r => r.name)
      })});
      for (const result of results) {
        state.pageUrl = result.result.pageUrl;
        state.preview = pageInfo(state.pageUrl).preview;
        for (const url of result.result.resources) await record(state, url);
        for (const video of result.result.videos) await record(state, video.url, '', '', {duration: video.duration});
      }
      await chrome.storage.session.set({watch: state});
      return {};
    }
    if (message.type === 'download') {
      const item = state.items.find(i => i.id === message.id);
      if (!item || item.kind !== 'video') throw new Error('该资源不能直接保存为完整视频。');
      const downloadId = await chrome.downloads.download({url: item.url, filename: filename(message.title || state.title, state.preview ? `预览-${message.episode || '分享片段'}` : message.episode, item.url), conflictAction: 'uniquify', saveAs: false});
      return {downloadId};
    }
    throw new Error('未知操作。');
  }).then(result => reply({ok: true, ...result}), error => reply({ok: false, error: error.message}));
  return true;
});
