import sys
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
from tasks import Tasks, Conflict
import server

class TaskTests(unittest.TestCase):
    def wait(self,tasks,job):
        for _ in range(200):
            value=tasks.get(job['id'])
            if value['state']!='running':return value
            time.sleep(.01)
        self.fail('task timed out')

    def test_independent_lanes_and_duplicate_rejection(self):
        tasks=Tasks();release=threading.Event();started=[]
        def execute(action,data,update,cancelled):
            started.append(action);release.wait(2);return {'ok':True}
        try:
            jobs=[tasks.submit(a,{},execute) for a in ('search','batch','local-merge')]
            self.assertCountEqual(started,['search','batch','local-merge'])
            with self.assertRaises(Conflict):tasks.submit('parse',{},execute)
            with self.assertRaises(Conflict):tasks.submit('merge',{},execute)
        finally:release.set()
        for j in jobs:self.assertEqual(self.wait(tasks,j)['state'],'done')

    def test_cancel_and_snapshot_isolation(self):
        tasks=Tasks();release=threading.Event()
        def execute(action,data,update,cancelled):
            update(progress={'items':[1]});release.wait(2);return {'cancelled':cancelled()}
        j=tasks.submit('batch',{},execute)
        snap=tasks.get(j['id']);snap['progress']['items'].append(2)
        self.assertEqual(tasks.get(j['id'])['progress']['items'],[1])
        tasks.cancel(j['id']);release.set()
        self.assertTrue(self.wait(tasks,j)['value']['cancelled'])

    def test_batch_runs_without_client_and_scrubs_secrets(self):
        tasks=Tasks()
        result={'id':'background','title':'测试','episodes':[{'id':str(i),'number':i} for i in range(1,4)]}
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'ROOT',Path(temp)),patch.dict(server.RESULTS,{'background':result}),patch.object(server,'resolve',return_value={'video':{'kind':'app','_app':{'contentKey':'SECRET'},'url':'SIGNED'}}),patch.object(server,'execute_operation',return_value={'path':'/tmp/test.mp4','duration':2}) as download:
            j=tasks.submit('batch',{'type':'resolve-download','resultId':'background','episodeIds':['1','2','3']},server.run_task)
            completed=self.wait(tasks,j)
            self.assertEqual(download.call_count,3)
            self.assertIn('成功 3',completed['value']['message'])
            self.assertNotIn('SECRET',str(completed));self.assertNotIn('SIGNED',str(completed))

    def test_429_stops_batch_and_failure_stays_failed(self):
        tasks=Tasks()
        result={'id':'limited','title':'测试','episodes':[{'id':str(i),'number':i} for i in range(1,4)]}
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'ROOT',Path(temp)),patch.dict(server.RESULTS,{'limited':result}),patch.object(server,'resolve',side_effect=server.RemoteError('限流',429)) as resolve:
            j=tasks.submit('batch',{'type':'resolve','resultId':'limited','episodeIds':['1','2','3']},server.run_task)
            value=self.wait(tasks,j)
            self.assertEqual(resolve.call_count,1);self.assertIn('上游限流',value['value']['message'])
            j=tasks.submit('batch',{'type':'invalid'},server.run_task)
            self.assertEqual(self.wait(tasks,j)['state'],'failed')

    def test_cancel_stops_after_current_episode(self):
        result={'id':'cancel','title':'测试','episodes':[{'id':str(i),'number':i} for i in range(1,4)]}
        stop=threading.Event()
        def download(action,data):
            stop.set()
            return {'path':'/tmp/test.mp4','duration':2}
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'ROOT',Path(temp)),patch.dict(server.RESULTS,{'cancel':result}),patch.object(server,'execute_operation',side_effect=download) as operation:
            value=server.run_task('batch',{'type':'download','resultId':'cancel','episodeIds':['1','2','3']},lambda **kw:None,stop.is_set)
            self.assertEqual(operation.call_count,1)
            self.assertIn('队列已停止：成功 1',value['message'])

    def test_persistent_empty_stops_remaining_episodes(self):
        result={'id':'empty','title':'test','episodes':[{'id':str(i),'number':i} for i in range(1,5)]}
        error=server.app_bridge.AppError('empty',200,code='EMPTY_RESPONSE')
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'ROOT',Path(temp)),patch.dict(server.RESULTS,{'empty':result}),patch.object(server,'resolve',side_effect=error) as resolve:
            value=server.run_task('batch',{'type':'resolve','resultId':'empty','episodeIds':['1','2','3','4']},lambda **kw:None,lambda:False)
            self.assertEqual(resolve.call_count,3)
            self.assertIn('连续三个视频持续返回空响应',value['message'])
            self.assertNotIn('error',value['result']['episodes'][3])

    def test_download_retries_failed_only_once_with_final_counts(self):
        result={'id':'retry','title':'test','episodes':[{'id':str(i),'number':i} for i in range(1,4)]}
        calls=[]
        def download(action,data):
            identity=data['episodeId'];calls.append(identity)
            if identity=='3' or (identity=='2' and calls.count('2')==1):raise ValueError('temporary')
            return {'path':'/tmp/test.mp4','duration':2}
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'ROOT',Path(temp)),patch.dict(server.RESULTS,{'retry':result}),patch.object(server,'execute_operation',side_effect=download):
            value=server.run_task('batch',{'type':'download','resultId':'retry','episodeIds':['1','2','3']},lambda **kw:None,lambda:False)
        self.assertEqual(calls,['1','2','3','2','3'])
        self.assertIn('成功 2，失败 1',value['message'])
        self.assertEqual(value['retried'],2)
        self.assertNotIn('error',value['result']['episodes'][1])
        self.assertIn('error',value['result']['episodes'][2])

    def test_empty_skips_without_retry_and_success_resets_streak(self):
        result={'id':'skip','title':'test','episodes':[{'id':str(i),'number':i} for i in range(1,7)]}
        calls=[]
        def download(action,data):
            calls.append(data['episodeId'])
            if data['episodeId'] in ('1','2','4','5'):raise server.app_bridge.AppError('empty',200,code='EMPTY_RESPONSE')
            return {'path':'/tmp/test.mp4','duration':2}
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'ROOT',Path(temp)),patch.dict(server.RESULTS,{'skip':result}),patch.object(server,'execute_operation',side_effect=download):
            value=server.run_task('batch',{'type':'download','resultId':'skip','episodeIds':[str(i) for i in range(1,7)]},lambda **kw:None,lambda:False)
        self.assertEqual(calls,['1','2','3','4','5','6'])
        self.assertEqual(value['retried'],0)
        self.assertIn('成功 2，失败 4',value['message'])

    def test_download_folder_prepared_before_failed_resolve(self):
        result={'id':'folder','title':'测试目录','episodes':[{'id':'1','number':1}]}
        with tempfile.TemporaryDirectory() as temp,patch.object(server,'ROOT',Path(temp)),patch.dict(server.RESULTS,{'folder':result}):
            def resolve(*args):
                self.assertTrue((Path(temp)/'downloads'/'测试目录').is_dir())
                raise server.app_bridge.AppError('empty',200,code='EMPTY_RESPONSE')
            with patch.object(server,'resolve',side_effect=resolve):
                value=server.run_task('batch',{'type':'resolve-download','resultId':'folder','episodeIds':['1']},lambda **kw:None,lambda:False)
            self.assertEqual(value['result']['downloadDirectory'],str(Path(temp)/'downloads'/'测试目录'))
