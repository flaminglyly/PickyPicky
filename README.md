# PickyPicky · 摘摘红果子

本地运行的短剧下载与视频整理工具，浏览器访问 `http://127.0.0.1:8765`。

## 功能

- 按剧名搜索、解析分享链接、选择剧集下载，显示后台任务状态。
- 本地视频多选、追加、排序、参数比较及历史合并记录。
- 保留源编码合并、仅转码差异文件、全量画质优先和 Mac 硬件编码方案。
- 实时显示合并阶段进度，任务结束弹窗提示。

接口可用范围由来源平台决定，不保证所有剧集可下载。差异编码拼接不能保证 QuickTime 兼容；FFmpeg 解码通过不等于所有播放器兼容。

## 安装与启动

需要 Python 3.9+、Node.js 18+、FFmpeg（包含 ffprobe）。本地文件选择使用 macOS 原生窗口。

```sh
npm ci --prefix pc --ignore-scripts
python3 -B pc/server.py
```

也可双击 `启动网页工具.command`，保持服务运行。网页刷新或关闭不会停止后台任务；服务重启会丢失当前任务和文件选择会话。

## 本地数据

下载文件位于 `pc/downloads/`，合并输出默认位于首个所选源文件目录。运行日志和合并历史位于 `pc/.runtime/`。这些数据、依赖目录及本机诊断报告均不提交到 GitHub。

匿名播放设备身份仅保留在服务内存中，不需要将账号 Cookie 写入仓库。

## 测试

```sh
python3 -B -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.cjs tests/*.test.mjs
```

## 开源组件

项目包含 GPL-3.0 组件，来源及本地修改见 [第三方声明](pc/vendor/NOTICE.md)，许可证全文随各组件保留。Node 依赖通过 `pc/package-lock.json` 锁定。

旧 Chrome 扩展保留在 `extension/`；当前主要入口是本地网页工具。
