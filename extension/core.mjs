export function safeUrl(value) {
  try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch { return null; }
}
export function mediaKind(url, mime = '') {
  const parsed = new URL(url);
  const path = parsed.pathname;
  const hint = parsed.searchParams.get('mime_type') || '';
  if (!mime && /^(video_mp4|video_webm)$/.test(hint)) mime = hint.replace('_', '/');
  if (/mpegurl/i.test(mime) || /\.m3u8$/i.test(path)) return 'hls';
  if (/dash\+xml/i.test(mime) || /\.mpd$/i.test(path)) return 'dash';
  if (/mp2t/i.test(mime) || /\.(ts|m4s)$/i.test(path)) return 'segment';
  if (/^video\/(mp4|webm|quicktime)(;|$)/i.test(mime) || /\.(mp4|webm|mov)$/i.test(path)) return 'video';
  return null;
}
export function cleanName(value) {
  return String(value || '').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').replace(/^\.+|[. ]+$/g, '').trim().slice(0, 80) || '未命名短剧';
}
export function filename(title, episode, url) {
  const ext = new URL(url).pathname.match(/\.(webm|mov|mp4)$/i)?.[1].toLowerCase() || 'mp4';
  return `红果短剧/${cleanName(title)}/${cleanName(episode)}.${ext}`;
}

export function pageInfo(url, title = '') {
  const u = new URL(url);
  const preview = /(^|\.)novelquickapp\.com$/.test(u.hostname) && u.pathname.includes('/video-animation-share');
  return {preview, title: title.match(/《(.+?)》/)?.[1] || title, label: preview ? '红果分享页预览（非完整剧集）' : ''};
}
