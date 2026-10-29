import test from 'node:test';
import assert from 'node:assert/strict';
import {safeUrl, mediaKind, cleanName, filename, pageInfo} from '../extension/core.mjs';
test('rejects executable, local and credential-bearing URLs', () => {
  for (const url of ['javascript:alert(1)', 'file:///tmp/a', 'blob:https://a/b', 'https://user:pass@example.com/a', 'bad']) assert.equal(safeUrl(url), null);
  assert.equal(safeUrl('https://example.com/a?token=x'), 'https://example.com/a?token=x');
});
test('classifies signed URLs and extensionless responses without treating segments as videos', () => {
  assert.equal(mediaKind('https://cdn.test/a.mp4?sign=1'), 'video');
  assert.equal(mediaKind('https://cdn.test/play?id=1', 'video/mp4'), 'video');
  assert.equal(mediaKind('https://cdn.test/a', 'application/vnd.apple.mpegurl'), 'hls');
  assert.equal(mediaKind('https://cdn.test/a.mpd'), 'dash');
  assert.equal(mediaKind('https://cdn.test/a.ts', 'video/mp2t'), 'segment');
  assert.equal(mediaKind('https://cdn.test/logo.png'), null);
});
test('filenames stay inside the downloads folder', () => {
  assert.equal(cleanName('..'), '未命名短剧');
  const name = filename('../../短剧', '../第1集', 'https://cdn.test/a.webm?x=1');
  assert.equal(name.split('/').length, 3);
  assert.ok(name.endsWith('.webm'));
  assert.ok(!name.includes('../'));
});

test('recognizes Hongguo extensionless MP4 and labels animation share as preview', () => {
  assert.equal(mediaKind('https://v3-share.qznovel.com/video/id/?mime_type=video_mp4&start=0&end=30'), 'video');
  const info = pageInfo('https://novelquickapp.com/hongguo/ug/pages/video-animation-share?vid=123', '红果短剧 ｜ 跟我一起免费看《测试剧》');
  assert.equal(info.preview, true);
  assert.equal(info.title, '测试剧');
  assert.equal(pageInfo('https://novelquickapp.com.evil.test/video-animation-share').preview, false);
});
