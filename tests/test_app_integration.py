import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import server

class AppTests(unittest.TestCase):
    def setUp(self):
        server.RESULTS['app-test']={'title':'测试剧','seriesId':'123','episodes':[{'id':'456','number':2,'video':None}]}
        self.media={'vid':'456','url':'https://cdn.qznovelvod.com/test','contentKey':'01'*16,'codec':'hevc','userAgent':'test'}
    def test_default_uses_app_and_hides_keys(self):
        with patch.object(server.TRAFFIC,'pace',return_value=True),patch.object(server.app_bridge,'resolve',return_value=(self.media,52.6)),patch.object(server,'read_player') as web:
            item=server.resolve('app-test','456')
            web.assert_not_called()
            self.assertEqual(item['video']['kind'],'app')
            self.assertIn('cacheUntil',item['video'])
            self.assertNotIn('expiresAt',item['video'])
            visible=server.public_payload(item)
            self.assertNotIn('_app',visible['video'])
            self.assertNotIn('contentKey',str(visible))
            self.assertNotIn('cdn.qznovelvod.com',str(visible))
    def test_app_rate_limit_updates_shared_cooldown(self):
        with patch.object(server.TRAFFIC,'pace',return_value=True),patch.object(server.TRAFFIC,'limited',return_value={'retryAfter':300}) as limited,patch.object(server.app_bridge,'resolve',side_effect=server.app_bridge.AppError('限流',429,'300')):
            with self.assertRaises(server.RemoteError) as err:server.resolve('app-test','456')
            self.assertEqual(err.exception.status,429)
            limited.assert_called_once_with('300','App 播放接口')
    def test_download_saves_processed_size(self):
        class Response(io.BytesIO):
            status=206
            headers={'Content-Type':'video/mp4','Content-Range':'bytes 0-2/3'}
        server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','duration':12,'_app':self.media}
        def decode(source,target,key):
            self.assertEqual(source.read_bytes(),b'enc')
            self.assertEqual(key,'01'*16)
            target.write_bytes(b'plain')
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server.shutil,'which',return_value='/bin/tool'),patch.object(server,'fetch',return_value=Response(b'enc')),patch.object(server.app_bridge,'decode',side_effect=decode),patch.object(server,'verify_mp4',return_value=12):
            result=server.download('app-test','456')
            self.assertEqual(result['bytes'],5)
            self.assertEqual(Path(result['path']).read_bytes(),b'plain')
    def test_unverified_redirect_tries_only_same_episode_candidate(self):
        other={**self.media,'url':'https://backup.qznovelvod.com/test'}
        self.media['variants']=[{k:v for k,v in self.media.items() if k!='variants'},other]
        server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','_app':self.media}
        calls=[]
        def attempt(video,candidate,target):
            calls.append(candidate['url'])
            if len(calls)==1:raise server.UnverifiedHost('unknown host')
            target.write_bytes(b'valid');return 12
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server.shutil,'which',return_value='/bin/tool'),patch.object(server,'_download_candidate',side_effect=attempt):
            saved=server.download('app-test','456')
            self.assertEqual(len(calls),2)
            self.assertEqual(saved['bytes'],5)
    def test_rate_limit_does_not_try_another_candidate(self):
        self.media['variants']=[dict(self.media),dict(self.media)]
        server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','_app':self.media}
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server.shutil,'which',return_value='/bin/tool'),patch.object(server,'_download_candidate',side_effect=server.RemoteError('限流',429)) as attempt:
            with self.assertRaises(server.RemoteError):server.download('app-test','456')
            self.assertEqual(attempt.call_count,1)
    def test_unknown_redirect_refreshes_app_once(self):
        server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','_app':self.media}
        def refresh(*args,**kwargs):
            server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','_app':self.media}
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server.shutil,'which',return_value='/bin/tool'),patch.object(server,'_download_candidate',side_effect=server.UnverifiedHost('unknown')),patch.object(server,'resolve',side_effect=refresh) as resolver:
            with self.assertRaises(server.UnverifiedHost):server.download('app-test','456')
            resolver.assert_called_once_with('app-test','456',provider='app')
            self.assertIsNone(server.RESULTS['app-test']['episodes'][0]['video'])
    def test_ten_minute_old_cache_refreshes_before_download(self):
        server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','cacheUntil':500,'_app':self.media}
        calls=[]
        def refresh(*args,**kwargs):
            calls.append('refresh')
            server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','cacheUntil':1120,'_app':self.media}
        def transfer(video,media,target):
            calls.append('download');target.write_bytes(b'valid');return 12
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'ROOT',Path(directory)),patch.object(server.time,'time',return_value=1000),patch.object(server.shutil,'which',return_value='/bin/tool'),patch.object(server,'resolve',side_effect=refresh),patch.object(server,'_download_candidate',side_effect=transfer):
            saved=server.download('app-test','456')
            self.assertEqual(calls,['refresh','download'])
            self.assertEqual(saved['bytes'],5)
    def test_renewal_429_stops_before_media_request(self):
        server.RESULTS['app-test']['episodes'][0]['video']={'kind':'app','source':'app','cacheUntil':1,'_app':self.media}
        with patch.object(server,'resolve',side_effect=server.RemoteError('限流',429)),patch.object(server,'_download_candidate') as transfer:
            with self.assertRaises(server.RemoteError):server.download('app-test','456')
            transfer.assert_not_called()
    def test_real_expiry_renews_once_and_rejects_still_expired_result(self):
        server.RESULTS['app-test']['episodes'][0]['video']={'kind':'direct','source':'web-fallback','expiresAt':1}
        def expired(*args,**kwargs):
            server.RESULTS['app-test']['episodes'][0]['video']={'kind':'direct','source':'web-fallback','expiresAt':1}
        with patch.object(server,'resolve',side_effect=expired) as refresh,patch.object(server,'_download_candidate') as transfer:
            with self.assertRaisesRegex(ValueError,'重新取址'):server.download('app-test','456')
            refresh.assert_called_once_with('app-test','456',provider='web')
            transfer.assert_not_called()
    def test_invalid_200_response_retried_only_once(self):
        error=server.app_bridge.AppError('invalid',200,code='INVALID_RESPONSE')
        for outcomes,success in [([error,(self.media,12)],True),([error,error],False)]:
            server.RESULTS['app-test']['episodes'][0]['video']=None
            with patch.object(server.TRAFFIC,'pace',return_value=True),patch.object(server.time,'sleep'),patch.object(server.app_bridge,'resolve',side_effect=outcomes) as call:
                if success:server.resolve('app-test','456')
                else:
                    with self.assertRaises(server.app_bridge.AppError):server.resolve('app-test','456')
                self.assertEqual(call.call_count,2)

    def test_private_filter_is_recursive(self):
        visible=server.public_payload({'episodes':[{'video':{'_app':self.media,'kind':'app'}}]})
        self.assertEqual(visible,{'episodes':[{'video':{'kind':'app'}}]})

if __name__=='__main__':unittest.main()

class EmptyResponseRetryTests(unittest.TestCase):
    def test_empty_retries_with_backoff_and_releases_lock(self):
        error=server.app_bridge.AppError('empty',200,code='EMPTY_RESPONSE')
        waits=[]
        def sleep(seconds):
            self.assertTrue(server.REQUEST_LOCK.acquire(False))
            server.REQUEST_LOCK.release();waits.append(seconds)
        with patch.object(server.TRAFFIC,'pace',return_value=True),patch.object(server.app_bridge,'resolve',side_effect=[error,error,({'url':'safe'},2)]),patch.object(server.time,'sleep',side_effect=sleep):
            self.assertEqual(server.resolve_app_with_retry('123')[1],2)
        self.assertEqual(waits,[10,30])
    def test_persistent_empty_is_bounded(self):
        error=server.app_bridge.AppError('empty',200,code='EMPTY_RESPONSE')
        with patch.object(server.TRAFFIC,'pace',return_value=True),patch.object(server.app_bridge,'resolve',side_effect=error) as call,patch.object(server.time,'sleep'):
            with self.assertRaises(server.app_bridge.AppError):server.resolve_app_with_retry('123')
        self.assertEqual(call.call_count,3)
