"""Local Node bridge; private media information never enters browser responses."""
import threading
import re
import diagnostics
import time
import json
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent

class AppError(ValueError):
    def __init__(self,message,status=None,retry_after=None,code=None):
        super().__init__(message);self.status=status;self.retry_after=retry_after;self.code=code

def _call(job, timeout=45):
    node=shutil.which('node')
    if not node:raise AppError('未找到 Node.js，请安装后重启网页工具。')
    try:
        response=subprocess.run([node,str(ROOT/'app-worker.cjs')],input=json.dumps(job),text=True,
                                capture_output=True,timeout=timeout,cwd=str(ROOT))
    except subprocess.TimeoutExpired:raise AppError('App 媒体操作超时，请稍后重试。') from None
    try:result=json.loads(response.stdout)
    except ValueError:raise AppError('App 模块未正常启动，请在 pc 目录执行 npm ci --ignore-scripts。') from None
    for trace in result.get('traces',[])[:2]:
        if not isinstance(trace,dict):continue
        safe={key:trace[key] for key in ('host','status','contentType','bodyBytes','responseFormat','proxyMode','proxyHost','proxyPort','responseHeaders','diagnosis','certainty','peerAddress','peerPort','tlsAuthorized','tlsPeerFingerprint','responseComplete','bodySha256','elapsedMs','code') if key in trace}
        diagnostics.event(ROOT,'App接口响应','received',episodeId=job.get('episodeId'),**safe)
    if not result.get('ok'):

        raise AppError(result.get('error','App 媒体操作失败'),result.get('status'),result.get('retryAfter'),result.get('code'))
    return result

_identity_lock = threading.Lock()
_identity = None
_identity_error = None

def playback_identity():
    # One registration per server lifetime, including failures. Never log or persist IDs.
    global _identity, _identity_error
    with _identity_lock:
        if _identity_error: raise _identity_error
        if _identity is None:
            try:
                identity = call({'action':'register'}).get('identity', {})
                if not all(isinstance(identity.get(k), str) and re.fullmatch(r'[0-9]{1,30}', identity[k]) and int(identity[k]) > 0 for k in ('device_id','iid')):
                    raise AppError('匿名播放设备响应无效。', code='DEVICE_REGISTRATION_FAILED')
                _identity = {k:identity[k] for k in ('device_id','iid','cdid')}
            except Exception as error:
                _identity_error = error
                raise
        return dict(_identity)

def resolve(episode_id):
    result=call({'action':'resolve','episodeId':episode_id,'identity':playback_identity()})
    media=result.get('media')
    if not isinstance(media,dict) or media.get('vid')!=episode_id or not media.get('url'):
        raise AppError('App 模块没有返回当前分集的媒体地址。')
    return media,result.get('duration')

def decode(source,target,key):
    return call({'action':'decode','input':str(source),'output':str(target),'key':key},timeout=180)


def call(job,timeout=45):
    stage={'resolve':'App取址','register':'匿名播放设备注册'}.get(job.get('action'),'媒体处理')
    started=time.monotonic()
    diagnostics.event(ROOT,stage,'start',episodeId=job.get('episodeId'))
    try:
        result=_call(job,timeout)
        diagnostics.event(ROOT,stage,'complete',elapsedMs=round((time.monotonic()-started)*1000),bytes=result.get('bytes'))
        return result
    except Exception as error:
        diagnostics.record(ROOT,error,stage,elapsedMs=round((time.monotonic()-started)*1000),status=getattr(error,'status',None),code=getattr(error,'code',None))
        raise
