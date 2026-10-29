import json
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import diagnostics

class DiagnosticTests(unittest.TestCase):
    def test_timeout_is_not_mislabeled_as_expiry(self):
        self.assertIn('读取超时',diagnostics.describe(URLError(socket.timeout('timed out'))))
    def test_media_timeout_is_distinct(self):
        self.assertIn('媒体工具',diagnostics.describe(subprocess.TimeoutExpired('ffmpeg',180)))
    def test_private_values_never_logged(self):
        with tempfile.TemporaryDirectory() as root:
            diagnostics.record(root,URLError('https://cdn.test/path?token=PRIVATE'),'视频下载',episodeId='123',host='cdn.test',url='PRIVATE',contentKey='PRIVATE')
            text=(Path(root)/'.runtime/failures.jsonl').read_text()
            self.assertNotIn('PRIVATE',text)
            self.assertEqual(json.loads(text)['stage'],'视频下载')
    def test_operation_and_failure_share_trace_and_stack(self):
        with tempfile.TemporaryDirectory() as root:
            token=diagnostics.begin()
            try:
                diagnostics.event(root,'App取址','start',url='SECRET')
                try:raise ValueError('SECRET')
                except ValueError as error:identifier=diagnostics.record(root,error,'App取址')
                entries=[json.loads(line) for line in (Path(root)/'.runtime/operations.jsonl').read_text().splitlines()]
                failure=json.loads((Path(root)/'.runtime/failures.jsonl').read_text())
                self.assertEqual(entries[0]['traceId'],failure['traceId'])
                self.assertEqual(failure['id'],identifier)
                self.assertEqual(failure['frames'][-1]['function'],'test_operation_and_failure_share_trace_and_stack')
                self.assertNotIn('SECRET',json.dumps(entries)+json.dumps(failure))
            finally:diagnostics.finish(token)
        self.assertIsNone(diagnostics.TRACE.get())

    def test_rotation_and_unwritable_destination(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            with patch.object(diagnostics,'MAX_BYTES',1):
                for _ in range(8):diagnostics.event(root,'HTTP操作','start')
            self.assertEqual(len(list((Path(root)/'.runtime').glob('operations.jsonl*'))),5)
            blocker=Path(root)/'file';blocker.write_text('x')
            diagnostics.event(blocker,'HTTP操作','start')
            self.assertEqual(diagnostics.record(blocker,ValueError(),'HTTP操作'),'记录失败')

    def test_dns_and_permissions_are_distinct(self):
        self.assertIn('域名解析失败',diagnostics.describe(URLError(socket.gaierror())))
        self.assertIn('权限',diagnostics.describe(PermissionError()))

if __name__=='__main__':unittest.main()
