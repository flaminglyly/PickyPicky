"""Extract only public video URLs explicitly bound to the requested episode."""
import json
import math
from html.parser import HTMLParser
from urllib.parse import urlsplit

class JsonLd(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.parts=[]; self.documents=[]
    def handle_starttag(self, tag, attrs):
        if tag=='script' and dict(attrs).get('type','').lower()=='application/ld+json':
            self.active=True; self.parts=[]
    def handle_data(self, data):
        if self.active:self.parts.append(data)
    def handle_endtag(self, tag):
        if tag=='script' and self.active:
            self.active=False
            try:self.documents.append(json.loads(''.join(self.parts)))
            except ValueError:pass

def nodes(value):
    if isinstance(value,list):
        for item in value:yield from nodes(item)
    elif isinstance(value,dict):
        if value.get('@type')=='VideoObject':yield value
        yield from nodes(value.get('@graph',[]))

def public_video(text, page, series_id, episode_id):
    seo=page.get('publicVideoSeo')
    if not isinstance(seo,dict) or seo.get('available') is not True:return None
    if str(page.get('vid'))!=episode_id or str(page.get('series_id'))!=series_id:return None
    if str(seo.get('seriesId'))!=series_id or str(seo.get('itemId'))!=episode_id:return None
    parser=JsonLd();parser.feed(text)
    for node in nodes(parser.documents):
        try:
            url=node['contentUrl']; media=urlsplit(url); origin=urlsplit(node.get('url',''))
            if media.scheme!='https' or media.hostname not in ('hongguoduanju.com','www.hongguoduanju.com'):continue
            if media.username or media.password or media.port not in (None,443):continue
            if not media.path.startswith(f'/video/public/{episode_id}/'):continue
            if origin.scheme!='https' or origin.hostname not in ('hongguoduanju.com','www.hongguoduanju.com'):continue
            if origin.username or origin.password or origin.port not in (None,443):continue
            if origin.path not in (f'/player/{series_id}',f'/player/{series_id}/{episode_id}'):continue
            duration=float(seo.get('durationSeconds',0))
            if not math.isfinite(duration) or duration<=0:continue
            return {'kind':'direct','url':url,'duration':duration,'format':'mp4',
                    'source':'web-public','referer':f'https://hongguoduanju.com/player/{series_id}/{episode_id}',
                    'width':seo.get('width'),'height':seo.get('height'),'verified':False}
        except (ValueError,TypeError,KeyError):continue
    return None
