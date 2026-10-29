import sys
import tempfile
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
from traffic import Traffic

class TrafficTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now=1700000000
        self.sleeps=[]
        self.path=Path(self.directory.name)/'cooldown.json'
        def sleep(seconds):self.sleeps.append(seconds);self.now+=seconds
        self.traffic=Traffic(self.path,clock=lambda:self.now,sleep=sleep)
    def test_global_pacing(self):
        self.assertTrue(self.traffic.pace());self.assertTrue(self.traffic.pace())
        self.assertEqual(self.sleeps,[3])
    def test_retry_after_not_shortened(self):
        state=self.traffic.limited('7200','视频 CDN')
        self.assertEqual(state['retryAfter'],7200)
        self.assertFalse(self.traffic.pace())
    def test_http_date(self):
        date=format_datetime(datetime.fromtimestamp(self.now+900,timezone.utc),usegmt=True)
        self.assertEqual(self.traffic.limited(date,'播放接口')['retryAfter'],900)
    def test_exponential_cooldown_and_restart_persistence(self):
        self.assertEqual(self.traffic.limited(None,'视频 CDN')['retryAfter'],300)
        self.now+=301
        self.assertEqual(self.traffic.limited('invalid','视频 CDN')['retryAfter'],600)
        restored=Traffic(self.path,clock=lambda:self.now)
        self.assertEqual(restored.state()['retryAfter'],600)
        self.assertEqual(restored.state()['source'],'视频 CDN')

if __name__=='__main__':unittest.main()
