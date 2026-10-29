import io,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import drama_search,server

class SearchTests(unittest.TestCase):
    def tearDown(self):drama_search.CACHE.clear()
    def test_official_result_mapping_and_deduplication(self):
        row={'keyword':'12345678','name':'<em>测试</em>短剧','video_data':{'series_cover':'https://p6-novel.byteimg.com/a.image','episode_cnt':10}}
        result=drama_search.parse_results({'searchList':[row,row],'hasMore':True})
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['items'][0]['title'],'测试短剧')
        self.assertEqual(result['items'][0]['shareLink'],'https://hongguoduanju.com/detail?series_id=12345678')
        self.assertTrue(result['hasMore'])
    def test_poster_rejects_local_and_non_https(self):
        for url in ('https://[bad','http://p6-novel.byteimg.com/a','https://127.0.0.1/a','https://p6-novel.byteimg.com.evil.test/a','https://user@p6-novel.byteimg.com/a','https://p6-novel.byteimg.com:8000/a'):
            self.assertEqual(drama_search.poster(url),'')
    def test_cache_does_not_repeat_request(self):
        with patch('drama_search.time.monotonic',return_value=10):
            def fetch(*args,**kwargs):return io.BytesIO(b'{"searchList":[],"hasMore":false}')
            with patch('builtins.print'):
                with patch.object(server,'fetch',side_effect=fetch) as call:
                    for _ in range(2):drama_search.search('测试',1,call)
                    self.assertEqual(call.call_count,1)
    def test_empty_response_and_unknown_shape_not_empty_search(self):
        for body in (b'',b'{}',b'{"searchList":[{"unknown":1}]}'):
            with self.assertRaises(ValueError):drama_search.search('测试',1,lambda *a,**k:io.BytesIO(body))
    def test_official_detail_catalog_and_identity(self):
        detail={'series_id':'12345678','series_name':'测试剧','episode_cnt':2,'vid_list':['123','456']}
        def fetch(*a,**k):
            data={'loaderData':{'detail_page':{'seriesDetail':detail}}}
            return io.BytesIO(('window._ROUTER_DATA = '+json.dumps(data)+';function runWindowFn(){}').encode())
        with patch.object(server,'fetch',side_effect=fetch):
            result=server.parse_share('https://hongguoduanju.com/detail?series_id=12345678')
            self.assertEqual([e['id'] for e in result['episodes']],['123','456'])
            self.assertEqual(result['seriesId'],'12345678')
        with self.assertRaisesRegex(ValueError,'不匹配'):
            drama_search.read_catalog('https://hongguoduanju.com/detail?series_id=99999999',fetch)

if __name__=='__main__':unittest.main()

class ExactSearchTests(unittest.TestCase):
    def test_exact_filter_keeps_full_title_only(self):
        from unittest.mock import patch
        import drama_search
        raw={'keyword':'剧名: 完结','items':[{'seriesId':'1','title':'剧名： 完结'},{'seriesId':'2','title':'剧名'},{'seriesId':'3','title':'剧名: 完结续集'}],'hasMore':True,'page':1}
        with patch.object(drama_search,'search',return_value=raw):
            result=drama_search.search_exact('剧名: 完结',1,None)
        self.assertEqual([x['seriesId'] for x in result['items']],['1'])
        self.assertTrue(result['hasMore'])

class RankedSearchTests(unittest.TestCase):
    def test_rank_exact_contains_similar_and_unrelated(self):
        import drama_search
        score=drama_search.match_score
        self.assertEqual(score('穿越八零：辣媳','穿越八零:辣媳'),1)
        self.assertGreater(score('穿越八零完结篇','穿越八零'),score('穿越九零','穿越八零'))
        self.assertGreater(score('穿越九零','穿越八零'),score('都市高手','穿越八零'))
    def test_ranked_search_preserves_fuzzy_results_and_cache(self):
        from unittest.mock import patch
        import drama_search
        raw={'keyword':'穿越八零','items':[{'title':'穿越九零'},{'title':'穿越八零完结篇'},{'title':'穿越八零'}],'hasMore':True}
        with patch.object(drama_search,'search',return_value=raw):result=drama_search.search_ranked('穿越八零',1,None)
        self.assertEqual([i['title'] for i in result['items']],['穿越八零','穿越八零完结篇','穿越九零'])
        self.assertNotIn('matchScore',raw['items'][0])

class SearchEndpointTests(unittest.TestCase):
    def tearDown(self):drama_search.CACHE.clear()
    def test_current_first_page_parameters_and_accept_header(self):
        calls=[]
        def fetch(url,**kwargs):
            calls.append((url,kwargs));return io.BytesIO(b'{"searchList":[],"hasMore":false}')
        drama_search.search('test',1,fetch)
        self.assertIn('aid=8662&query=test',calls[0][0])
        self.assertNotIn('page=',calls[0][0])
        self.assertEqual(calls[0][1]['extra_headers']['Accept'],'application/json')
    def test_search_configuration_error_has_specific_message_and_log(self):
        from urllib.error import HTTPError
        from unittest.mock import Mock
        body=b'{"code":"signature_configuration_unavailable","message":"Search risk control is temporarily unavailable."}'
        error=HTTPError('https://hongguoduanju.com/api/search/result',503,'Service Unavailable',{'content-type':'application/json','x-tt-logid':'test123'},io.BytesIO(body))
        opener=Mock();opener.open.side_effect=error
        with patch.object(server.TRAFFIC,'pace',return_value=True),patch.object(server,'build_opener',return_value=opener),patch.object(server.diagnostics,'record') as record:
            with self.assertRaisesRegex(server.RemoteError,'signature_configuration_unavailable'):
                server.fetch(error.url)
        self.assertEqual(record.call_args.kwargs['upstreamCode'],'signature_configuration_unavailable')
        self.assertEqual(record.call_args.args[2],'搜索接口')
