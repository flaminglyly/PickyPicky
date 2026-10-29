import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import merge_history
import merge_video

class HistoryTests(unittest.TestCase):
    def test_default_name_and_custom_extension(self):
        self.assertRegex(merge_video.output_filename('我的剧集'),r'^我的剧集-\d{8}-\d{6}\.mp4$')
        self.assertEqual(merge_video.output_filename('x','新名称'),'新名称.mp4')
        self.assertEqual(merge_video.output_filename('x','新名称.MP4'),'新名称.mp4')
        for name in ('../bad','/tmp/a','..','.mp4','a\nb','a'*221):
            with self.assertRaises(ValueError):merge_video.output_filename('x',name)
    def test_older_outputs_are_indexed_once(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'downloads'/'合并视频';folder.mkdir(parents=True)
            (folder/'旧合并.mp4').write_bytes(b'old')
            (folder/'临时.part.mp4').write_bytes(b'part')
            self.assertEqual(len(merge_history.list_records(root)),1)
            self.assertEqual(len(merge_history.list_records(root)),1)
            self.assertEqual(merge_history.list_records(root)[0]['sources'],[])

    def test_history_persists_order_failure_and_missing_file(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'result.mp4';target.write_bytes(b'fake')
            merge_history.record(root,[Path('2.mp4'),Path('1.mp4')],result={'path':str(target),'duration':2,'bytes':4})
            merge_history.record(root,[Path('bad.mp4')],error=ValueError())
            rows=merge_history.list_records(root)
            self.assertEqual(rows[0]['status'],'failure')
            self.assertEqual(rows[1]['sources'],['2.mp4','1.mp4'])
            self.assertTrue(rows[1]['exists'])
            self.assertTrue(rows[1]['createdAt'].endswith('+08:00'))
            target.unlink()
            self.assertFalse(merge_history.list_records(root)[1]['exists'])
