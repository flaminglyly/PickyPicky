import sys
import unittest
import io
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'pc'))
import server

class ParserTests(unittest.TestCase):
    def test_streamed_data(self):
        p=server.Page()
        p.feed('<script data-fn-args="[&quot;route&quot;,&quot;pageData&quot;,{&quot;series_data&quot;:{&quot;title&quot;:&quot;测试剧&quot;},&quot;chapter_ids&quot;:[&quot;123&quot;]}]"></script>')
        self.assertEqual(p.data['chapter_ids'],['123'])
    def setUp(self):
        server.COOLDOWN_UNTIL=0
        server.RESULTS['test']={'title':'测试剧','seriesId':'456','episodes':[{'id':'123','number':1,'video':None}]}
    def test_wrong_catalog_rejected(self):
        with patch.object(server,'read_player',return_value=('url',{'seriesDetail':{'series_name':'其他剧','vid_list':['123']}})):
            with self.assertRaisesRegex(ValueError,'不匹配'): server.resolve('test','123',provider='web')
    def test_compatible_address(self):
        page={'seriesDetail':{'series_name':'测试剧','vid_list':['123'],'accessible_episode_cnt':1}}
        responses=[{'play_info':{'main_url':'https://cdn.qznovelvod.com/v','kid':'sensitive','format':'dash','duration':52.617}},
                   {'main_url':'https://cdn.qznovelvod.com/plain','url_expire':9999999999}]
        with patch.object(server,'read_player',return_value=('url',page)),patch.object(server,'api_post',side_effect=responses):
            video=server.resolve('test','123',provider='web')['video']
        self.assertEqual(video['kind'],'direct')
        self.assertNotIn('kid',video)
    def test_nonaccessible_episode_never_requests_fallback(self):
        page={'seriesDetail':{'series_name':'测试剧','vid_list':['123'],'accessible_episode_cnt':0}}
        with patch.object(server,'read_player',return_value=('url',page)),patch.object(server,'api_post',return_value={'play_info':{'main_url':'https://cdn.qznovelvod.com/v','kid':'secret','format':'dash'}}) as api:
            self.assertEqual(server.resolve('test','123',provider='web')['video']['kind'],'encrypted')
            self.assertEqual(api.call_count,1)
    def test_rate_limit_propagated_and_stale_address_cleared(self):
        page={'seriesDetail':{'series_name':'测试剧','vid_list':['123'],'accessible_episode_cnt':1}}
        server.RESULTS['test']['episodes'][0]['video']={'url':'stale'}
        with patch.object(server,'read_player',return_value=('url',page)),patch.object(server,'api_post',side_effect=server.RemoteError('限流',429)):
            with self.assertRaises(server.RemoteError): server.resolve('test','123',provider='web')
        self.assertIsNone(server.RESULTS['test']['episodes'][0]['video'])
    def test_no_download_of_encrypted_stream(self):
        server.RESULTS['test']['episodes'][0]['video']={'kind':'encrypted'}
        with self.assertRaisesRegex(ValueError,'加密 DASH'):server.download('test','123')
    def test_range_download_assembles_and_checks_file(self):
        class Response(io.BytesIO):
            status=206
            def __init__(self,body,content_range):
                super().__init__(body);self.headers={'Content-Type':'video/mp4','Content-Range':content_range}
        server.RESULTS['test']['episodes'][0]['video']={'kind':'direct','url':'https://cdn.qznovelvod.com/v','duration':12}
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server.shutil,'which',return_value='/bin/tool'),patch.object(server,'fetch',side_effect=[Response(b'abc','bytes 0-2/6'),Response(b'def','bytes 3-5/6')]),patch.object(server,'verify_mp4',return_value=12) as verify,patch.object(server.time,'sleep'):
            saved=server.download('test','123')
            self.assertEqual(Path(saved['path']).read_bytes(),b'abcdef')
            self.assertEqual(saved['bytes'],6)
            verify.assert_called_once()
    def test_truncated_range_removed(self):
        class Response(io.BytesIO):
            status=206
            headers={'Content-Type':'video/mp4','Content-Range':'bytes 0-5/6'}
        server.RESULTS['test']['episodes'][0]['video']={'kind':'direct','url':'https://cdn.qznovelvod.com/v'}
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server.shutil,'which',return_value='/bin/tool'),patch.object(server,'fetch',return_value=Response(b'abc')):
            with self.assertRaisesRegex(ValueError,'截断'):server.download('test','123')
            self.assertEqual(list(Path(directory).rglob('*.part')),[])
            self.assertEqual(list(Path(directory).rglob('*.mp4')),[])
    def test_valid_playback_cache_avoids_network(self):
        server.RESULTS['test']['episodes'][0]['video']={'kind':'direct','source':'web-fallback','expiresAt':9999999999}
        with patch.object(server,'read_player') as remote:
            self.assertEqual(server.resolve('test','123',provider='web')['video']['kind'],'direct')
            remote.assert_not_called()
    def test_share_cache_avoids_network(self):
        url='https://novelquickapp.com/s/test'
        server.SHARE_CACHE[url]=(9999999999,'test')
        try:
            with patch.object(server,'read_page') as remote:
                self.assertEqual(server.parse_share(url)['title'],'测试剧')
                remote.assert_not_called()
        finally:server.SHARE_CACHE.pop(url,None)
    def test_stream_without_clipping_is_unknown(self):
        self.assertEqual(server.video_info('https://v3-share.qznovel.com/a?mime_type=video_mp4')['kind'],'unknown')
        self.assertEqual(server.video_info('https://v3-share.qznovel.com/a?end=30')['kind'],'preview')
    def test_restricted_destinations(self):
        for url in ['http://novelquickapp.com/a','https://127.0.0.1/a','https://novelquickapp.com.evil.test/a','https://user:pass@novelquickapp.com/a']:
            with self.assertRaises(ValueError): server.validate(url)

if __name__=='__main__': unittest.main()
