import {safeUrl} from './core.mjs';
const $ = id => document.getElementById(id);
const status = text => { $('status').textContent = text; };
async function send(type, data = {}) {
  const response = await chrome.runtime.sendMessage({type, ...data});
  if (!response?.ok) throw new Error(response?.error || '后台未响应');
  return response;
}
function action(id, fn) {
  $(id).addEventListener('click', async () => {
    $(id).disabled = true;
    try { await fn(); } catch (error) { status(error.message); }
    finally { $(id).disabled = false; }
  });
}
async function render() {
  const {watch} = await send('state');
  $('list').replaceChildren();
  if (!watch) { status('尚未开始检测'); return; }
  if (!$('title').value) $('title').value = watch.title;
  status(`${watch.preview ? '此页面仅提供分享预览，无法获取完整剧集。' : ''}正在检测标签页 ${watch.tabId} · 已发现 ${watch.items.length} 个资源。切换剧集后播放再刷新。`);
  for (const [index, item] of watch.items.entries()) {
    const card = document.createElement('div'); card.className = 'card';
    const heading = document.createElement('strong'); heading.textContent = `${item.kind === 'video' ? '视频直链' : item.kind.toUpperCase() + ' 分段流'} · 资源 ${index + 1}`;
    const source = document.createElement('p'); source.textContent = `${new URL(item.url).hostname}${item.duration ? ' · ' + item.duration.toFixed(1) + ' 秒' : ''}${watch.preview ? ' · 分享预览' : ''}`;
    const episode = document.createElement('input'); episode.placeholder = '集数或文件名（请核对实际播放集数）'; episode.value = `资源-${index + 1}`; episode.setAttribute('aria-label', '集数或文件名');
    const button = document.createElement('button'); button.textContent = item.kind === 'video' ? (watch.preview ? '下载预览片段' : '下载视频') : '暂不支持合并'; button.disabled = item.kind !== 'video';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await send('download', {id: item.id, title: $('title').value, episode: episode.value}); status('已提交 Chrome 下载，请在下载列表确认完成。'); }
      catch (error) { status(error.message); }
      finally { button.disabled = false; }
    });
    card.append(heading, source, episode, button); $('list').append(card);
  }
}
action('open', async () => {
  const match = $('share').value.match(/https?:\/\/[^\s<>"，。]+/i);
  const url = match && safeUrl(match[0]);
  if (!url) throw new Error('分享文案中没有有效的 HTTP/HTTPS 链接。');
  await chrome.tabs.create({url});
  status('已打开分享页面，请在该页面打开插件并开始检测。');
});
action('start', async () => {
  const granted = await chrome.permissions.request({origins: ['http://*/*', 'https://*/*']});
  if (!granted) throw new Error('未获得网页访问权限，无法检测跨域视频资源。');
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  await send('start', {tabId: tab.id, title: $('title').value});
  await send('scan'); await render();
});
action('scan', async () => { await send('scan'); await render(); });
action('stop', async () => { await send('stop'); await render(); });
render().catch(error => status(error.message));
