import sys,unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import app_bridge

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.old=(app_bridge._identity,app_bridge._identity_error)
        app_bridge._identity=app_bridge._identity_error=None
    def tearDown(self):
        app_bridge._identity,app_bridge._identity_error=self.old
    def test_concurrent_calls_share_registration(self):
        identity={'device_id':'1234567890123456789','iid':'9876543210987654321','cdid':'uuid'}
        with patch.object(app_bridge,'call',return_value={'identity':identity}) as call:
            with ThreadPoolExecutor(max_workers=6) as pool:
                results=list(pool.map(lambda _:app_bridge.playback_identity(),range(12)))
            self.assertTrue(all(x==identity for x in results));call.assert_called_once()
            results[0]['iid']='changed'
            self.assertEqual(app_bridge.playback_identity(),identity)
    def test_failure_cached_without_new_registration(self):
        error=app_bridge.AppError('registration',code='DEVICE_REGISTRATION_FAILED')
        with patch.object(app_bridge,'call',side_effect=error) as call:
            for _ in range(3):
                with self.assertRaises(app_bridge.AppError):app_bridge.playback_identity()
            call.assert_called_once()
    def test_numeric_or_zero_identity_rejected(self):
        for value in (123,'0','bad'):
            app_bridge._identity_error=None
            with patch.object(app_bridge,'call',return_value={'identity':{'device_id':value,'iid':'123','cdid':'uuid'}}):
                with self.assertRaises(app_bridge.AppError):app_bridge.playback_identity()
