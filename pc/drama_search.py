"""Search and catalog parsing for the public Hongguo website."""
import html
import json
import re
import time
import unicodedata
from urllib.parse import urlencode,urlsplit

CACHE={}
SEARCH_ENDPOINT="https://hongguoduanju.com/api/search/result"

def text(value):return html.unescape(re.sub(r'<[^>]*>','',str(value or ''))).strip()

def poster(value):
    if not isinstance(value,str):return ''
    try:
        u=urlsplit(value)
        valid=u.scheme=='https' and (u.hostname or '').endswith('.byteimg.com') and not u.username and not u.password and u.port in (None,443)
    except ValueError:return ''
    return value if valid else ''

def parse_results(data):
    if not isinstance(data,dict) or not isinstance(data.get('searchList'),list):raise ValueError('红果搜索未返回有效结果，请稍后重试。')
    results=[];seen=set()
    for item in data['searchList']:
        if not isinstance(item,dict):continue
        video=item.get('video_data') or item
        if not isinstance(video,dict):continue
        identity=str(video.get('series_id') or item.get('keyword') or '')
        title=text(video.get('series_name') or video.get('series_title') or item.get('name'))
        if not re.fullmatch(r'[0-9]{6,30}',identity) or not title or identity in seen:continue
        seen.add(identity)
        results.append({'seriesId':identity,'title':title,'poster':poster(video.get('series_cover') or video.get('cover')),
                        'episodeCount':video.get('episode_cnt') if isinstance(video.get('episode_cnt'),int) else None,
                        'description':text(video.get('series_intro'))[:1000],
                        'shareLink':'https://hongguoduanju.com/detail?'+urlencode({'series_id':identity})})
    if data['searchList'] and not results:raise ValueError('红果搜索结果格式发生变化，暂时无法识别。')
    total=str(data.get('totalCount',''))
    return {'items':results,'hasMore':data.get('hasMore') is True,'total':int(total) if total.isdigit() and len(total)<10 else None}

def search(keyword,page,fetch):
    if not isinstance(keyword,str):raise ValueError('请输入短剧名称。')
    keyword=unicodedata.normalize('NFKC',keyword).strip()
    if not 1<=len(keyword)<=100:raise ValueError('请输入 1 至 100 字的短剧名称。')
    if type(page) is not int or not 1<=page<=100:raise ValueError('搜索页码无效。')
    key=(keyword,page);cached=CACHE.get(key)
    if cached and cached[0]>time.monotonic():return cached[1]
    params={'aid':'8662','query':keyword}
    if page>1:params['page']=page
    url=SEARCH_ENDPOINT+'?'+urlencode(params)
    with fetch(url,referer='https://hongguoduanju.com/',extra_headers={'Accept':'application/json'}) as response:raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('搜索响应过大，已停止读取。')
    try:data=json.loads(raw)
    except ValueError:raise ValueError('红果搜索返回空响应或非 JSON 内容，请稍后重试。') from None
    result={**parse_results(data),'keyword':keyword,'page':page,'source':'红果短剧官网'}
    if len(CACHE)>=40:CACHE.pop(next(iter(CACHE)))
    CACHE[key]=(time.monotonic()+300,result)
    return result

def detail_url(value):
    u=urlsplit(value)
    return u.hostname in ('hongguoduanju.com','www.hongguoduanju.com') and u.path=='/detail'

def read_catalog(url,fetch):
    from urllib.parse import parse_qs
    identity=parse_qs(urlsplit(url).query).get('series_id',[''])[0]
    if not re.fullmatch(r'[0-9]{6,30}',identity):raise ValueError('官网剧集链接缺少有效剧集 ID。')
    canonical='https://hongguoduanju.com/detail?'+urlencode({'series_id':identity})
    with fetch(canonical) as response:raw=response.read(4_000_001)
    if len(raw)>4_000_000:raise ValueError('官网详情页面过大。')
    match=re.search(r'_ROUTER_DATA\s*=\s*(\{.*?\});\s*function runWindowFn',raw.decode('utf-8'),re.S)
    if not match:raise ValueError('官网详情页没有可识别的剧集目录。')
    data=json.loads(match[1]).get('loaderData',{})
    detail=next((item['seriesDetail'] for item in data.values() if isinstance(item,dict) and isinstance(item.get('seriesDetail'),dict)),{})
    ids=detail.get('vid_list')
    if str(detail.get('series_id'))!=identity:raise ValueError('官网详情返回的剧集 ID 不匹配。')
    if not isinstance(ids,list) or not 1<=len(ids)<=3000 or not all(re.fullmatch(r'[0-9]{1,30}',str(i)) for i in ids) or len(set(map(str,ids)))!=len(ids):
        raise ValueError('官网未返回有效剧集目录。')
    return {'title':text(detail.get('series_name')),'count':detail.get('episode_cnt'),
            'pageUrl':canonical,'seriesId':identity,'episodes':[{'id':str(i),'number':n+1,'video':None} for n,i in enumerate(ids)],
            'notice':'目录来自红果官网。请选择剧集后解析或下载，实际可用性以取址和下载结果为准。'}

def exact_title(value):
    return unicodedata.normalize('NFKC',text(value)).strip()

def search_exact(keyword,page,fetch):
    result=search(keyword,page,fetch)
    return {**result,'items':[item for item in result['items'] if exact_title(item['title'])==exact_title(result['keyword'])],
            'total':None,'exactMatch':True}

def match_score(title,keyword):
    from difflib import SequenceMatcher
    def normalized(value):
        return ''.join(c for c in exact_title(value).casefold() if c.isalnum())
    title,keyword=normalized(title),normalized(keyword)
    if not title or not keyword:return 0
    if title==keyword:return 1.0
    ratio=SequenceMatcher(None,keyword,title,autojunk=False).ratio()
    if keyword in title:return round(.8+.19*len(keyword)/len(title),6)
    return round(.79*ratio,6)

def search_ranked(keyword,page,fetch):
    result=search(keyword,page,fetch)
    items=[{**item,'matchScore':match_score(item['title'],result['keyword'])} for item in result['items']]
    return {**result,'items':sorted(items,key=lambda item:-item['matchScore']),'exactMatch':False}
