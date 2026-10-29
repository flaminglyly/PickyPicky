"""Safe failure diagnostics: no URLs, query parameters, cookies or media keys."""
import contextvars
import time
import traceback
import json
import socket
import ssl
import subprocess
import threading
import uuid
from datetime import datetime,timezone
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import URLError

LOCK=threading.Lock()

def describe(error):
    reason=error.reason if isinstance(error,URLError) else error
    if isinstance(error,subprocess.TimeoutExpired):return '媒体工具处理超时，请稍后重试。'
    if isinstance(reason,(TimeoutError,socket.timeout)):return '网络连接或读取超时；这不代表视频地址已过期。'
    if isinstance(reason,ssl.SSLCertVerificationError):return 'HTTPS 证书校验失败，已停止请求。'
    if isinstance(reason,ssl.SSLError):return 'TLS 连接或数据传输异常，请稍后重试；不代表证书校验失败。'
    if isinstance(reason,socket.gaierror):return '域名解析失败，请检查网络连接。'
    if isinstance(reason,IncompleteRead):return '视频响应在传输过程中被截断。'
    if isinstance(reason,ConnectionError):return '网络连接被中断，请稍后重试。'
    if isinstance(reason,PermissionError):return '文件访问被拒绝，请检查下载目录权限。'
    if isinstance(reason,OSError) and getattr(reason,'errno',None)==28:return '磁盘空间不足，请清理下载目录所在磁盘。'
    if isinstance(error,URLError):return '网络连接失败，请检查网络或代理设置。'
    if isinstance(error,ValueError):return str(error) or '返回的数据格式不符合预期。'
    if isinstance(error,(KeyError,StopIteration)):return '当前剧集会话不存在，请重新解析分享链接。'
    return f'处理出现异常（{type(error).__name__}），请提供诊断编号以便定位。'

TRACE=contextvars.ContextVar('diagnostic_trace',default=None)
MAX_BYTES=5_000_000
BACKUPS=4
FIELDS=('upstreamCode','consecutiveEmpty','proxyMode','proxyHost','proxyPort','responseHeaders','diagnosis','certainty','peerAddress','peerPort','tlsAuthorized','tlsPeerFingerprint','responseComplete','bodySha256','elapsedMs','code','attempt','retryDelay','code','contentType','bodyBytes','responseFormat','sslReason','sslLibrary','scheme','port','episodeId','host','rangeStart','rangeEnd','action','status','bytes','elapsedMs','duration','errorType','reasonType','frames')

def begin():
    return TRACE.set(uuid.uuid4().hex[:16])

def finish(token):
    TRACE.reset(token)

def _write(root,name,entry):
    try:
        folder=Path(root)/'.runtime';folder.mkdir(parents=True,exist_ok=True)
        log=folder/name
        with LOCK:
            if log.exists() and log.stat().st_size>=MAX_BYTES:
                for index in range(BACKUPS,0,-1):
                    source=log if index==1 else folder/f'{name}.{index-1}'
                    if source.exists():source.replace(folder/f'{name}.{index}')
            with log.open('a',encoding='utf-8') as out:
                out.write(json.dumps(entry,ensure_ascii=False)+'\n')
        return True
    except OSError:return False

def event(root,stage,state,**context):
    entry={'time':datetime.now(timezone.utc).isoformat(),'traceId':TRACE.get(),
           'stage':stage,'event':state}
    entry.update({key:context[key] for key in FIELDS if key in context})
    _write(root,'operations.jsonl',entry)
    return entry

def record(root,error,stage,**context):
    identifier=uuid.uuid4().hex[:12]
    frames=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
            for frame in traceback.extract_tb(error.__traceback__)]
    reason=getattr(error,'reason',error)
    if isinstance(reason,ssl.SSLError):
        context.update(sslReason=getattr(reason,'reason',None),sslLibrary=getattr(reason,'library',None))
    entry=event(root,stage,'failure',errorType=type(error).__name__,
                reasonType=type(getattr(error,'reason',None)).__name__,frames=frames,**context)
    entry['id']=identifier
    # Keep error messages, source code and local variables out of persistent logs.
    return identifier if _write(root,'failures.jsonl',entry) else '记录失败'
