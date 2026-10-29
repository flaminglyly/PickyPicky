"""Local Hongguo share-page reader. Python 3.9+, standard library only."""
import json
import copy
from tasks import Tasks, LANES, Conflict
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
import cdn_transport
import socket
import ssl
from http.client import IncompleteRead
from urllib.error import URLError
import diagnostics
import app_bridge
import merge_video
import merge_history
import drama_search
import local_library
from public_video import public_video
from traffic import Traffic
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
from urllib.error import HTTPError
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(24)
RESULTS = {}
LOCK = threading.Lock()
PAGE_HOSTS = {'novelquickapp.com', 'www.novelquickapp.com', 'hongguoduanju.com', 'www.hongguoduanju.com'}
TRAFFIC = Traffic(ROOT / ".runtime" / "cooldown.json")
REQUEST_LOCK = threading.Lock()
TASKS = Tasks()
SHARE_CACHE = {}

class UnverifiedHost(ValueError):
    pass

class RemoteError(ValueError):
    def __init__(self, message, status=502):
        super().__init__(message); self.status = status

def validate(url, media=False, redirected=False):
    u = urlsplit(url)
    host = u.hostname or ''
    allowed = host in PAGE_HOSTS if not media else (host.endswith(('.qznovel.com', '.qznovelvod.com', '.fqnovelvod.com', '.douyinvod.com')) or (host in ('hongguoduanju.com','www.hongguoduanju.com') and bool(re.fullmatch(r'/video/public/[0-9]+/[^?#]+',u.path))))
    if media and redirected and cdn_transport.observed_cdn(host):allowed=True
    port_allowed=u.port in (None,443) or (media and redirected and host.endswith('.ctydoh.cn') and u.port==20002)
    if not port_allowed:raise UnverifiedHost(f'CDN 端口未通过验证：{host}:{u.port}。已停止请求。')
    if u.scheme != 'https' or not allowed or u.username or u.password:
        raise UnverifiedHost(f'域名未通过验证：{host or "无效域名"}。已停止请求。')
    return url

class Redirects(HTTPRedirectHandler):
    max_redirections=5
    max_repeats=2
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        diagnostics.event(ROOT,'重定向','received',host=urlsplit(newurl).hostname,status=code,scheme=urlsplit(newurl).scheme,port=urlsplit(newurl).port)
        media=getattr(req,'media',False)
        hops=getattr(req,'cdn_hops',0)+1
        if hops>5:raise UnverifiedHost('视频跳转超过 5 次，已停止请求。')
        destination=urlsplit(newurl)
        if media and destination.scheme=='http' and cdn_transport.observed_cdn(destination.hostname or '') and not destination.username and not destination.password and destination.port in (None,80):
            # CDN scheduling sometimes advertises HTTP. Probe only its HTTPS
            # equivalent; never send the media request over plaintext.
            newurl=urlunsplit(('https',destination.hostname,destination.path,destination.query,destination.fragment))
        validate(newurl,media,redirected=media)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        new.media = media
        new.cdn_hops = hops
        if media:
            # Never carry credentials to another hostname. Range and User-Agent
            # are the only inherited request headers for media redirects.
            for key in list(new.headers):
                if key.lower() not in ('range','user-agent','accept'):del new.headers[key]
        return new

def fetch(url, media=False, body=None, referer=None, extra_headers=None):
    validate(url, media)
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'}
    if referer: headers['Referer'] = referer
    headers.update(extra_headers or {})
    if body is not None:
        headers.update({'Content-Type':'application/json', 'Origin':'https://hongguoduanju.com'})
    req = Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    req.media = media
    source = '视频 CDN' if media else ('搜索接口' if urlsplit(url).path.startswith('/api/search/') else '播放接口' if '/api/' in urlsplit(url).path else '网页解析')
    with REQUEST_LOCK:
        if not TRAFFIC.pace():
            state=TRAFFIC.state()
            raise RemoteError(f"{state['source']}限流冷却中，还需等待约 {state['retryAfter']} 秒。",429)
        try:
            started=time.monotonic()
            diagnostics.event(ROOT,source,'start',host=urlsplit(url).hostname)
            opener=build_opener(ProxyHandler({}),cdn_transport.PublicHTTPSHandler(),Redirects()) if media else build_opener(Redirects())
            response=opener.open(req, timeout=30)
            diagnostics.event(ROOT,source,'headers',host=urlsplit(url).hostname,status=response.status,elapsedMs=round((time.monotonic()-started)*1000))
            return response
        except URLError as error:
            # HTTPError is also a URLError; keep status handling below.
            if isinstance(error,HTTPError):
                upstream_code=None
                response_headers={}
                if source=='搜索接口':
                    for key in ('server','via','content-type','content-length','retry-after','x-tt-logid','x-request-id'):
                        value=str(error.headers.get(key,'') or '')
                        if re.fullmatch(r'[a-zA-Z0-9_.: /;,=\-]{1,160}',value):response_headers[key]=value
                    try:
                        raw=error.read(8193)
                        payload=json.loads(raw) if len(raw)<=8192 else {}
                        code=payload.get('code') if isinstance(payload,dict) else None
                        if isinstance(code,str) and re.fullmatch(r'[a-zA-Z0-9_\-]{1,80}',code):upstream_code=code
                    except (ValueError,OSError):pass
                diagnostics.record(ROOT,error,source,host=urlsplit(url).hostname,status=error.code,responseHeaders=response_headers,upstreamCode=upstream_code)
                if source=='搜索接口' and error.code==503 and upstream_code=='signature_configuration_unavailable':
                    raise RemoteError('红果官网搜索风控服务暂时不可用（HTTP 503，signature_configuration_unavailable）。官网搜索也可能失败，请稍后重试；可使用已有分享链接解析目录。',error.code) from None
                if error.code==429:
                    state=TRAFFIC.limited(error.headers.get('Retry-After'),source)
                    raise RemoteError(f"{source}返回 HTTP 429，暂停至少 {state['retryAfter']} 秒；队列已停止。",429) from None
                raise RemoteError(f'搜索服务暂时不可用（HTTP {error.code}），请稍后重试。' if source=='搜索接口' else f'上游返回 HTTP {error.code}，未取得有效播放资源。',error.code) from None
            if media and isinstance(error.reason,ssl.SSLError):
                diagnostics.record(ROOT,error,'CDN HTTPS校验',host=urlsplit(url).hostname)
                raise UnverifiedHost('CDN 的 HTTPS 连接或证书校验失败，未降级为明文下载。') from error
            raise

def api_post(path, body, referer):
    with fetch('https://hongguoduanju.com'+path, body=body, referer=referer) as response:
        raw = response.read(1_000_001)
    if len(raw)>1_000_000: raise ValueError('接口响应过大。')
    try: data=json.loads(raw)
    except ValueError: raise ValueError('播放接口没有返回有效 JSON。') from None
    if not isinstance(data,dict): raise ValueError('播放接口响应格式异常。')
    base=data.get('base_resp',data.get('BaseResp',{}))
    if not isinstance(base,dict) or base.get('StatusCode',0)!=0: raise ValueError('播放接口返回业务错误。')
    return data

def read_player(series_id, episode_id):
    if not re.fullmatch(r'[0-9]+',series_id) or not re.fullmatch(r'[0-9]+',episode_id):
        raise ValueError('剧集 ID 格式异常。')
    url=f'https://hongguoduanju.com/player/{series_id}/{episode_id}'
    with fetch(url) as response: raw=response.read(4_000_001)
    if len(raw)>4_000_000: raise ValueError('页面过大。')
    match=re.search(r'_ROUTER_DATA\s*=\s*(\{.*?\});\s*function runWindowFn',raw.decode('utf-8'),re.S)
    if not match: raise ValueError('播放器页面没有可识别的路由数据。')
    routes=json.loads(match[1]).get('loaderData',{})
    data=next((v for v in routes.values() if isinstance(v,dict) and 'seriesDetail' in v),None)
    if not data or str(data.get('series_id'))!=series_id or str(data.get('vid'))!=episode_id:
        raise ValueError('播放器返回的剧集 ID 不匹配。')
    data['_publicVideo']=public_video(raw.decode('utf-8'),data,series_id,episode_id)
    return url,data

class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.data = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != 'script' or 'data-fn-args' not in attrs: return
        try: args = json.loads(attrs['data-fn-args'])
        except (ValueError, TypeError): return
        if isinstance(args, list) and len(args)>2 and isinstance(args[2], dict) and 'series_data' in args[2]:
            self.data = args[2]

def read_page(url):
    with fetch(url) as response:
        final = response.url
        raw = response.read(4_000_001)
    if len(raw)>4_000_000: raise ValueError('页面过大，停止解析。')
    parser = Page(); parser.feed(raw.decode('utf-8'))
    if not parser.data: raise ValueError('页面没有可识别的剧集数据，可能已失效或要求在 App 中打开。')
    data = parser.data
    base = data.get('BaseResp', {})
    if base.get('StatusCode', 0) != 0: raise ValueError('红果页面接口返回失败。')
    return final, data

def video_info(url):
    validate(url, True)
    q = parse_qs(urlsplit(url).query)
    # Only explicitly clipped streams can be identified from the present page schema.
    clipped = 'end' in q or 'start' in q
    return {'url': url, 'kind': 'preview' if clipped else 'unknown',
            'clipEnd': q.get('end', [''])[0]}

def parse_share(text):
    match = re.search(r'https://[^\s<>"，。]+', text)
    if not match: raise ValueError('请粘贴有效的红果分享链接。')
    cache_key=validate(match[0])
    with LOCK:
        cached=SHARE_CACHE.get(cache_key)
        if cached and cached[0]>time.time() and cached[1] in RESULTS:
            return RESULTS[cached[1]]
    if drama_search.detail_url(cache_key):
        result={'id':uuid.uuid4().hex,**drama_search.read_catalog(cache_key,fetch)}
    else:
        url, data = read_page(cache_key)
        series = data['series_data']; ids = data.get('chapter_ids', [])
        if not isinstance(ids,list) or len(ids)>3000: raise ValueError('剧集目录格式异常。')
        used = str(data.get('used_chapter_id', ''))
        item = video_info(series['play_url']) if series.get('play_url') else None
        entries = [{'id': str(cid), 'number': i+1, 'video': item if str(cid)==used else None} for i,cid in enumerate(ids)]
        result = {'id': uuid.uuid4().hex, 'title': series.get('title','未命名短剧'),
                  'count': series.get('serial_count'), 'pageUrl':url, 'episodes':entries,
                  'seriesId':parse_qs(urlsplit(url).query).get('video_id',[''])[0],
                  'notice':'默认使用匿名设备 App 取址方案。请选择剧集后解析或下载；遇限流停止队列，未知跳转会显示域名。' }
    with LOCK:
        if len(RESULTS)>=20: RESULTS.pop(next(iter(RESULTS)))
        RESULTS[result['id']] = result
        SHARE_CACHE[cache_key]=(time.time()+300,result['id'])
        if len(SHARE_CACHE)>40: SHARE_CACHE.pop(next(iter(SHARE_CACHE)))
    return result

def resolve_app_with_retry(episode_id):
    for attempt in range(3):
        try:
            with REQUEST_LOCK:
                if not TRAFFIC.pace():
                    state=TRAFFIC.state()
                    raise RemoteError(f"{state['source']}限流冷却中，还需等待约 {state['retryAfter']} 秒。",429)
                try:
                    return app_bridge.resolve(episode_id)
                except app_bridge.AppError as error:
                    if error.status==429:
                        state=TRAFFIC.limited(error.retry_after,'App 播放接口')
                        raise RemoteError(f"App 接口限流，暂停至少 {state['retryAfter']} 秒。",429) from None
                    raise
                finally:
                    with TRAFFIC.lock: TRAFFIC.next_request=max(TRAFFIC.next_request,time.time()+3)
        except app_bridge.AppError as error:
            empty=error.code=='EMPTY_RESPONSE' and error.status==200
            if not empty and not (error.code=='INVALID_RESPONSE' and error.status==200 and attempt==0):raise
            if attempt==2:raise
            delay=(10,30)[attempt] if empty else 3
            diagnostics.event(ROOT,'App取址','retry',episodeId=episode_id,status=error.status,code=error.code,attempt=attempt+2,retryDelay=delay)
            # Release the network lock during backoff so other features can proceed.
            time.sleep(delay)

def resolve(result_id, episode_id, provider='app'):
    with LOCK:
        result = RESULTS[result_id]
        entry = next(e for e in result['episodes'] if e['id']==episode_id)
        series_id=result.get('seriesId','')
        cached=entry.get('video')
        if cached and ((provider=='app' and cached.get('source')=='app') or (provider=='web' and cached.get('source','').startswith('web-'))) and float(cached.get('cacheUntil') or cached.get('expiresAt') or 0)>time.time()+60:
            return entry
        # Invalidate stale addresses before attempting a fresh resolution.
        entry['video']=None
    if not series_id: raise ValueError('缺少整剧 ID，请重新解析分享地址。')
    if provider not in ('app','web'): raise ValueError('未知解析方案。')
    if provider=='app':
        media,duration=resolve_app_with_retry(episode_id)
        validate(media['url'],True)
        video={'kind':'app','source':'app','codec':media.get('codec'),'duration':duration,
               'quality':media.get('quality'),'resolvedAt':time.time(),'cacheUntil':time.time()+120,'_app':media}
        with LOCK: entry['video']=video
        return entry
    referer,page=read_player(series_id,episode_id)
    detail=page['seriesDetail']
    ids=[str(v) for v in detail.get('vid_list',[])]
    if episode_id not in ids or detail.get('series_name')!=result['title']:
        raise ValueError('播放器返回的剧名或目录不匹配。')
    if page.get('_publicVideo'):
        with LOCK: entry['video']={**page['_publicVideo'],'resolvedAt':time.time(),'cacheUntil':time.time()+120}
        return entry
    info=api_post('/api/video/protected/play-info',{'series_id':series_id,'item_id':episode_id,'definition':'720p'},referer).get('play_info')
    if not isinstance(info,dict) or not info.get('main_url'): raise ValueError('接口没有返回播放资源。')
    validate(info['main_url'],True)
    encrypted=bool(info.get('player_access_key') or info.get('kid') or info.get('format')=='dash')
    video={'kind':'encrypted' if encrypted else 'unknown','duration':info.get('duration'),
           'format':info.get('format'),'definition':info.get('definition'),'width':info.get('width'),
           'height':info.get('height'),'expiresAt':info.get('expires_at'), 'source':'web-play-info'}
    # Use the browser's public compatibility route only for episodes declared accessible.
    accessible=detail.get('accessible_episode_cnt',0)
    if isinstance(accessible,int) and ids.index(episode_id)<accessible:
        try:
            fallback=api_post('/api/video/protected/fallback-play-info',{'item_id':episode_id},referer)
            url=fallback.get('main_url','')
            validate(url,True)
            clipped='end' in parse_qs(urlsplit(url).query)
            video.update(url=url,kind='preview' if clipped else 'direct',source='web-fallback',
                         expiresAt=fallback.get('url_expire'),referer=referer,verified=False,format='mp4')
        except RemoteError as error:
            if error.status==429: raise
            video['note']='兼容地址暂不可用；仅返回加密播放信息。'
        except ValueError:
            video['note']='兼容接口未返回可下载地址。'
    else:
        video['note']='网页未声明此集可用兼容播放；当前仅提供加密流信息，不支持下载。'
    with LOCK: entry['video']=video
    return entry

def verify_mp4(path):
    executable=shutil.which('ffprobe')
    if not executable: raise ValueError('需要 ffprobe 校验下载文件，请先安装 FFmpeg。')
    completed=subprocess.run([executable,'-v','error','-show_entries','format=duration:stream=codec_type,codec_name',
                              '-of','json',str(path)],capture_output=True,timeout=30)
    if completed.returncode: raise ValueError('下载文件未通过媒体校验。')
    info=json.loads(completed.stdout)
    streams=info.get('streams',[])
    if not any(x.get('codec_type')=='video' for x in streams) or not any(x.get('codec_type')=='audio' for x in streams):
        raise ValueError('下载文件缺少音频或视频轨。')
    duration=float(info.get('format',{}).get('duration',0))
    if duration<=0: raise ValueError('下载文件时长异常。')
    decoder=shutil.which('ffmpeg')
    if not decoder: raise ValueError('需要 ffmpeg 完整解码校验视频。')
    checked=subprocess.run([decoder,'-v','error','-xerror','-i',str(path),'-f','null','-'],capture_output=True,timeout=180)
    if checked.returncode: raise ValueError('下载内容截断、加密或损坏，未通过完整解码校验，未保存为成功文件。')
    return duration

def prepare_download_folder(title):
    folder=ROOT/'downloads'/clean(title)
    folder.mkdir(parents=True,exist_ok=True)
    diagnostics.event(ROOT,'下载目录','ready')
    return folder

def download(result_id, episode_id, allow_refresh=True):
    with LOCK:
        result=RESULTS[result_id]
        entry=next(e for e in result['episodes'] if e['id']==episode_id)
        video=entry.get('video')
        saved=entry.get('download')
    if saved and Path(saved['path']).is_file() and Path(saved['path']).stat().st_size==saved['bytes']:
        return {**saved,'cached':True}
    if not video or video['kind'] not in ('preview','direct','app'):
        raise ValueError('请先解析为兼容 MP4 地址；加密 DASH 暂不支持下载。')
    stale_cache=bool(video.get('cacheUntil')) and float(video['cacheUntil'])<=time.time()+5
    near_expiry=bool(video.get('expiresAt')) and float(video['expiresAt'])<=time.time()+30
    if stale_cache or near_expiry:
        if not allow_refresh:
            raise ValueError('重新取址后仍未获得可用地址，请稍后再试。')
        provider='app' if video.get('source')=='app' else 'web'
        with LOCK: entry['video']=None
        # Resolve only when this episode reaches the front of the download queue.
        # Do not label a local cache deadline as upstream expiry or retry a 429.
        resolve(result_id,episode_id,provider=provider)
        return download(result_id,episode_id,allow_refresh=False)
    if not shutil.which('ffprobe'): raise ValueError('需要 ffprobe 校验视频，请先安装 FFmpeg。')
    folder=prepare_download_folder(result['title'])
    prefix='预览-' if video['kind']=='preview' else ''
    target=folder/f"{prefix}第{entry['number']:03d}集-{uuid.uuid4().hex[:6]}.mp4"
    private=video.get('_app') or {}
    candidates=(private.get('variants') or [private])[:5] if video['kind']=='app' else [private]
    for index,candidate in enumerate(candidates):
        if video['kind']=='app' and candidate.get('vid')!=episode_id:
            raise ValueError('候选媒体的分集 ID 不匹配。')
        try:
            duration=_download_candidate(video,candidate,target)
            break
        except UnverifiedHost:
            if index+1==len(candidates):
                if video['kind']=='app' and allow_refresh:
                    with LOCK: entry['video']=None
                    resolve(result_id,episode_id,provider='app')
                    return download(result_id,episode_id,allow_refresh=False)
                with LOCK: entry['video']=None
                raise
            # Only try another address returned for this same episode. Never ignore 429.
            continue
    saved={'path':str(target),'bytes':target.stat().st_size,'duration':duration}
    with LOCK: entry['download']=saved
    return saved

def _download_candidate(video,private,target):
    partial=target.with_suffix('.part')
    decoded=target.with_suffix('.decoded.part')
    media_url=private.get('url') if video['kind']=='app' else video['url']
    if not media_url: raise ValueError('没有可下载地址，请重新解析此集。')
    stage='视频下载'
    start=None; end=None
    try:
        size=0; total=None; chunk_size=1024*1024
        with partial.open('wb') as out:
            while total is None or size<total:
                start=size; end=start+chunk_size-1
                for attempt in range(3):
                    try:
                        with fetch(media_url,True,referer=video.get('referer'),extra_headers={**({'User-Agent':private['userAgent']} if private.get('userAgent') else {}),'Range':f'bytes={start}-{end}'}) as response:
                            if not any(t in response.headers.get('Content-Type','').lower() for t in ('video/','application/octet-stream')):
                                raise ValueError('服务器没有返回视频内容。')
                            if response.status==206:
                                match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                                if not match: raise ValueError('视频分段范围响应异常。')
                                lo,hi,length=map(int,match.groups())
                                if lo!=start or hi>end or hi<lo or hi>=length or (total is not None and total!=length):
                                    raise ValueError('视频分段顺序或文件大小不一致。')
                                total=length
                                if total>500_000_000: raise ValueError('文件超过 500MB。')
                                chunk=response.read(chunk_size+1)
                                if len(chunk)!=hi-lo+1: raise ValueError('视频分段内容被截断。')
                                out.write(chunk);size+=len(chunk)
                            elif response.status==200 and start==0:
                                for chunk in iter(lambda:response.read(256*1024),b''):
                                    size+=len(chunk)
                                    if size>500_000_000: raise ValueError('文件超过 500MB。')
                                    out.write(chunk)
                                total=size
                            else: raise ValueError('服务器没有返回有效视频分段。')
                        break
                    except (URLError,TimeoutError,ConnectionError,IncompleteRead,ssl.SSLError) as error:
                        reason=error.reason if isinstance(error,URLError) else error
                        if isinstance(reason,ssl.SSLCertVerificationError):raise
                        diagnostics.record(ROOT,error,'分段重试',rangeStart=start,rangeEnd=end)
                        if attempt==2:raise
                        # Roll back an interrupted HTTP 200 body before retrying.
                        out.seek(start);out.truncate();size=start
                        time.sleep(3*(attempt+1))
                diagnostics.event(ROOT,'视频分段','complete',host=urlsplit(media_url).hostname,rangeStart=start,rangeEnd=size-1,bytes=size-start)
                if size<total: time.sleep(3)
        if not size: raise ValueError('服务器返回空视频。')
        if video['kind']=='app' and private.get('contentKey'):
            stage='媒体处理'
            app_bridge.decode(partial,decoded,private['contentKey'])
            partial.unlink()
            decoded.rename(partial)
        stage='媒体校验'
        diagnostics.event(ROOT,stage,'start')
        duration=verify_mp4(partial)
        diagnostics.event(ROOT,stage,'complete',duration=duration,bytes=partial.stat().st_size)
        expected=float(video.get('duration') or 0)
        if video['kind'] in ('direct','app') and expected and abs(duration-expected)>max(2,expected*.05):
            raise ValueError(f'下载文件时长 {duration:.3f} 秒，与页面或接口标注的 {expected:.3f} 秒不一致，未保存为完整剧集。')
        partial.rename(target)
    except Exception as error:
        identifier=diagnostics.record(ROOT,error,stage,episodeId=private.get('vid'),host=urlsplit(media_url).hostname,rangeStart=start,rangeEnd=end)
        partial.unlink(missing_ok=True); decoded.unlink(missing_ok=True)
        # Preserve typed errors used by the same-source refresh and 429 control flow.
        if isinstance(error,ValueError):raise
        raise ValueError(f'{stage}失败：{diagnostics.describe(error)}（诊断编号 {identifier}）') from error
    return duration

def clean(value):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(value)).strip('. ')[:100] or '未命名'

def public_payload(value):
    if isinstance(value,dict):
        return {k:public_payload(v) for k,v in value.items() if not k.startswith('_') and k not in ('url','referer','userAgent','contentKey','variants')}
    if isinstance(value,list): return [public_payload(v) for v in value]
    return value


def execute_operation(action, data):
    path="/api/"+action
    if path=='/api/search':return drama_search.search_ranked(data.get('keyword'),data.get('page',1),fetch)
    if path=='/api/local-folder': return local_library.choose_files(data.get("libraryId"))
    if path=='/api/local-compare':
        return merge_video.merge_compare.compare(local_library.selected(data.get('libraryId'),data.get('fileIds')))
    if path=='/api/local-merge':
        paths=local_library.selected(data.get('libraryId'),data.get('fileIds'))
        return merge_video.merge_files(ROOT,paths,output_name=data.get('outputName'),mode=data.get('mode','stream-copy'))
    if path=='/api/parse': return parse_share(data['share'])
    if path=='/api/resolve': return resolve(data['resultId'],data['episodeId'],data.get('provider','app'))
    if path=='/api/merge':
        ids=data.get('episodeIds')
        if not isinstance(ids,list) or not all(isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):
            raise ValueError('所选剧集列表无效。')
        with LOCK:
            result=RESULTS[data['resultId']]
            entries=[dict(e) for e in result['episodes'] if e['id'] in ids]
            title=clean(result['title'])
        if len(entries)!=len(ids):raise ValueError('所选剧集不属于当前目录。')
        return merge_video.merge(ROOT,title,entries)
    if path=='/api/download':
        provider=data.get('provider','app')
        with LOCK: title=RESULTS[data['resultId']]['title']
        prepare_download_folder(title)
        with LOCK:
            item=next(e for e in RESULTS[data['resultId']]['episodes'] if e['id']==data['episodeId'])
            cached=item.get('video') or {}
            has_saved=bool(item.get('download'))
        if not has_saved and (not cached or (provider=='app' and cached.get('source')!='app') or (provider=='web' and cached.get('source')=='app')):
            resolve(data['resultId'],data['episodeId'],provider)
        return download(data['resultId'],data['episodeId'])
    raise ValueError("未知操作。")

def run_task(action, data, update, cancelled):
    progress_token=merge_video.merge_progress.REPORT.set(update)
    token=diagnostics.begin()
    diagnostics.event(ROOT,'后台任务','start',action=action)
    try:
        if action != 'batch': return public_payload(execute_operation(action,data))
        ids=data.get('episodeIds')
        kind=data.get('type')
        if kind not in ('resolve','download','resolve-download') or not isinstance(ids,list) or not ids or not all(isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):
            raise ValueError('剧集队列参数无效。')
        with LOCK:
            result=RESULTS[data['resultId']]
            if not set(ids)<=set(e['id'] for e in result['episodes']): raise ValueError('剧集不属于当前目录。')
            view=copy.deepcopy(public_payload(result))
        if kind!='resolve':
            view['downloadDirectory']=str(prepare_download_folder(view['title']))
            update(progress={'result':view,'message':'下载目录已准备：'+view['downloadDirectory']})
        selected=[e for e in view['episodes'] if e['id'] in ids]
        for e in view['episodes']: e['selected']=e['id'] in ids
        success=failed=0
        limited=False
        unavailable=False
        consecutive_empty=0
        retry_entries=[]
        retried=0
        for retry_round in range(2):
            if retry_round and (kind=='resolve' or limited or unavailable or cancelled() or not retry_entries):break
            round_entries=selected if not retry_round else list(retry_entries)
            retry_entries=[]
            for index,entry in enumerate(round_entries):
                if cancelled(): break
                if retry_round:
                    retried+=1
                    diagnostics.event(ROOT,'失败补试','start',episodeId=entry['id'],attempt=2)
                payload={'resultId':data['resultId'],'episodeId':entry['id'],'provider':data.get('provider','app')}
                phase='resolve' if kind!='download' else 'download'
                update(progress={'result':view,'message':f"{'补试' if retry_round else '正在处理'}第 {entry['number']} 集 · {index+1}/{len(round_entries)}"})
                try:
                    if kind!='download':
                        entry['video']=public_payload(resolve(payload['resultId'],entry['id'],payload['provider'])).get('video')
                    if kind!='resolve' and cancelled(): break
                    if kind!='resolve':
                        phase='download'
                        saved=execute_operation('download',payload)
                        entry['saved']=f"校验通过 · {saved['duration']:.3f} 秒 · 已保存：{saved['path']}"
                    entry.pop('error',None)
                    success+=1
                    consecutive_empty=0
                    if retry_round: failed-=1
                except Exception as error:
                    identifier=diagnostics.record(ROOT,error,'后台剧集',episodeId=entry['id'])
                    entry['error']=f"{diagnostics.describe(error)}（诊断编号 {identifier}，追踪编号 {diagnostics.TRACE.get()}）"
                    if phase=='resolve': entry['video']=None
                    if not retry_round: failed+=1
                    if getattr(error,'code',None)=='EMPTY_RESPONSE':
                        consecutive_empty+=1
                        unavailable=consecutive_empty>=3
                        diagnostics.event(ROOT,'连续空响应','stop' if unavailable else 'skip',episodeId=entry['id'],consecutiveEmpty=consecutive_empty)
                    else:
                        consecutive_empty=0
                        retry_entries.append(entry)
                    if getattr(error,'status',None)==429: limited=True
                update(progress={'result':view,'message':f"{'补试' if retry_round else '已处理'} {index+1}/{len(round_entries)} 集"})
                if limited or unavailable: break
        message=f"{'上游限流，队列已停止' if limited else '连续三个视频持续返回空响应，队列已停止' if unavailable else '队列已停止' if cancelled() else '队列完成'}：成功 {success}，失败 {failed}。"
        if retried:message+=f' 已执行自动补试（{retried} 集，每集最多一轮）。'
        return {'result':view,'message':message,'retried':retried,**TRAFFIC.state()}
    except Exception as error:
        identifier=diagnostics.record(ROOT,error,'后台任务',action=action)
        update(error=f'{diagnostics.describe(error)}（诊断编号 {identifier}，追踪编号 {diagnostics.TRACE.get()}）',state='failed',retryAfter=TRAFFIC.state()['retryAfter'])
        return None
    finally:
        merge_video.merge_progress.REPORT.reset(progress_token)
        diagnostics.event(ROOT,'后台任务','end',action=action)
        diagnostics.finish(token)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass # do not log signed URLs
    def json(self, value, code=200):
        if diagnostics.TRACE.get():
            value={**value,'traceId':diagnostics.TRACE.get()}
        if diagnostics.TRACE.get():diagnostics.event(ROOT,'HTTP响应','success' if code<400 else 'failure',status=code)
        payload = json.dumps(public_payload(value), ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(payload)
    def do_GET(self):
        if self.headers.get('Host') != '127.0.0.1:8765': return self.json({'error':'Invalid host'},403)
        files = {'/':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript'), '/style.css':('style.css','text/css'), '/versions.json':('versions.json','application/json; charset=utf-8')}
        if self.path not in files: return self.json({'error':'Not found'},404)
        name, mime = files[self.path]; body = (ROOT/'web'/name).read_bytes()
        if name=='index.html':
            version=json.loads((ROOT/'web'/'versions.json').read_text())['version']
            body=body.replace(b'__TOKEN__',TOKEN.encode()).replace(b'__VERSION__',version.encode())
        self.send_response(200); self.send_header('Content-Type',mime)
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://*.byteimg.com; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.headers.get('Host')!='127.0.0.1:8765' or self.headers.get('X-Local-Token')!=TOKEN:
            return self.json({'error':'请从本机工具页面发起操作。'},403)
        if self.path=='/api/merge-history':
            return self.json({'records':merge_history.list_records(ROOT)})
        if self.path=='/api/status':
            return self.json(TRAFFIC.state())
        if self.path in ('/api/tasks', '/api/task', '/api/task-start', '/api/task-cancel'):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<16384: raise ValueError('请求大小异常。')
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict): raise ValueError('请求格式异常。')
                if self.path=='/api/tasks': return self.json({'tasks':TASKS.list()})
                if self.path=='/api/task': return self.json(TASKS.get(data.get('id')))
                if self.path=='/api/task-cancel': return self.json(TASKS.cancel(data.get('id')))
                if not isinstance(data.get('data'),dict): raise ValueError('任务参数无效。')
                return self.json(TASKS.submit(data.get('action'),data['data'],run_task))
            except Exception as error:
                return self.json({'error':diagnostics.describe(error)},409 if isinstance(error,Conflict) else 400)
        gate=TASKS.locks.get(LANES.get(self.path.removeprefix('/api/')))
        if gate is None: return self.json({'error':'Not found'},404)
        if not gate.acquire(blocking=False):
            return self.json({'error':'此功能已有任务运行，其他功能仍可使用。'},409)
        token=diagnostics.begin()
        started=time.monotonic()
        diagnostics.event(ROOT,'HTTP操作','start',action=self.path if self.path in ('/api/parse','/api/resolve','/api/download','/api/merge','/api/local-folder','/api/local-merge','/api/search') else 'unknown')
        try: self.handle_operation()
        finally:
            diagnostics.event(ROOT,'HTTP操作','end',elapsedMs=round((time.monotonic()-started)*1000))
            diagnostics.finish(token)
            gate.release()
    def handle_operation(self):
        if self.headers.get('Host')!='127.0.0.1:8765' or self.headers.get('X-Local-Token')!=TOKEN:
            return self.json({'error':'请从本机工具页面发起操作。'},403)
        data={}
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<16384: raise ValueError('请求大小异常。')
            data=json.loads(self.rfile.read(length))
            diagnostics.event(ROOT,'任务参数','received',episodeId=data.get('episodeId'),action=self.path if self.path in ('/api/parse','/api/resolve','/api/download','/api/merge','/api/local-folder','/api/local-merge','/api/search') else 'unknown')
            return self.json(execute_operation(self.path.removeprefix('/api/'),data))
        except Exception as error:
            identifier=diagnostics.record(ROOT,error,'HTTP操作',episodeId=data.get('episodeId') if isinstance(data,dict) else None,action=self.path if self.path in ('/api/parse','/api/resolve','/api/download','/api/merge','/api/local-folder','/api/local-merge','/api/search') else 'unknown')
            message=diagnostics.describe(error)
            message+=f'（诊断编号 {identifier}，追踪编号 {diagnostics.TRACE.get()}）'
            return self.json({'error':message or '没有匹配的剧集。','diagnosticId':identifier,'upstreamStatus':getattr(error,'status',None),**(TRAFFIC.state() if getattr(error,'status',None)==429 else {})},429 if getattr(error,'status',None)==429 else 400)

if __name__=='__main__':
    print('本地工具：http://127.0.0.1:8765（Ctrl+C 停止）',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
