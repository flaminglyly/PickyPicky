import sys,unittest,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import merge_progress
@unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required')
class ProgressTests(unittest.TestCase):
 def test_ffmpeg_progress_reaches_completion(self):
  events=[];token=merge_progress.REPORT.set(lambda **kw:events.append(kw['progress']))
  try:
   result=merge_progress.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=32x32:d=1','-f','null','-'],1,10,'校验')
  finally:merge_progress.REPORT.reset(token)
  self.assertEqual(result.returncode,0);self.assertEqual(events[0]['percent'],0);self.assertEqual(events[-1]['percent'],100)
  self.assertGreaterEqual(len(events),3)
