import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import merge_video

class MergeValidationTests(unittest.TestCase):
    def test_gaps_and_duplicates_rejected_before_io(self):
        for numbers in ([1],[1,3],[2,2]):
            with self.assertRaises(ValueError):merge_video.merge(Path('/tmp'),'test',[{'number':n} for n in numbers])
    def test_missing_episode_rejected(self):
        with tempfile.TemporaryDirectory() as root,patch.object(merge_video.shutil,'which',return_value='tool'):
            with self.assertRaisesRegex(ValueError,'尚未下载'):
                merge_video.merge(root,'test',[{'number':1},{'number':2}])

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class RealMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=self.root/'downloads'/"测试'剧";self.folder.mkdir(parents=True)
        self.source=self.folder/'第001集-aaaaaa.mp4'
        command=['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=25:d=0.4','-f','lavfi','-i','sine=frequency=500:duration=0.4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(self.source)]
        subprocess.run(command,check=True,capture_output=True)
        self.second=self.folder/'第002集-bbbbbb.mp4';shutil.copyfile(self.source,self.second)
    def tearDown(self):self.temp.cleanup()
    def hashes(self,path):
        result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_packets','-show_data_hash','sha256','-of','json',str(path)],capture_output=True,check=True)
        return [p['data_hash'] for p in json.loads(result.stdout)['packets']]
    def test_reverse_selection_sorted_and_encoded_packets_unchanged(self):
        result=merge_video.merge(self.root,self.folder.name,[{'number':2},{'number':1}])
        self.assertEqual(result['episodes'],[1,2]);self.assertEqual(result['mode'],'stream-copy')
        self.assertTrue(self.source.exists() and self.second.exists())
        self.assertEqual(self.hashes(result['path']),self.hashes(self.source)*2)
        self.assertFalse(list(self.folder.glob('*.part.mp4')))
        self.assertFalse(list(self.folder.glob('.merge-*')))
    def test_local_files_keep_explicit_order_without_episode_numbers(self):
        self.second.unlink()
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=320x180:r=25:d=0.4','-f','lavfi','-i','sine=frequency=500:duration=0.4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(self.second)],check=True,capture_output=True)
        result=merge_video.merge_files(self.root,[self.second,self.source])
        self.assertEqual(result['count'],2)
        self.assertEqual(self.hashes(result['path']),self.hashes(self.second)+self.hashes(self.source))
        self.assertEqual(Path(result['path']).parent,self.folder.resolve())

    def test_local_merge_supports_mixed_source_folders(self):
        other=self.root/'other.mp4';shutil.copyfile(self.second,other)
        result=merge_video.merge_files(self.root,[self.source,other])
        self.assertEqual(Path(result['path']).parent,self.source.parent.resolve())
        self.assertEqual(self.hashes(result['path']),self.hashes(self.source)+self.hashes(other))

    def test_custom_name_saved_and_existing_output_not_overwritten(self):
        import merge_history
        result=merge_video.merge_files(self.root,[self.source,self.second],output_name='我的合集')
        self.assertEqual(Path(result['path']).name,'我的合集.mp4')
        self.assertEqual(merge_history.list_records(self.root)[0]['path'],result['path'])
        before=Path(result['path']).read_bytes()
        with self.assertRaisesRegex(ValueError,'同名文件'):
            merge_video.merge_files(self.root,[self.source,self.second],output_name='我的合集.mp4')
        self.assertEqual(Path(result['path']).read_bytes(),before)

    def test_incompatible_parameters_rejected(self):
        original=merge_video.probe
        def probe(path):
            streams,duration=original(path)
            if path==self.second.resolve():streams[0]['width']=640
            return streams,duration
        with patch.object(merge_video,'probe',side_effect=probe):
            with self.assertRaisesRegex(ValueError,'参数不一致'):merge_video.merge(self.root,self.folder.name,[{'number':1},{'number':2}])
        self.assertFalse(list(self.folder.glob('合并-*')))
    def test_compatible_normalizes_resolution_and_frame_rate(self):
        self.second.unlink()
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=320x184:r=30:d=0.4','-f','lavfi','-i','sine=frequency=700:duration=0.4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(self.second)],check=True,capture_output=True)
        result=merge_video.merge_files(self.root,[self.source,self.second],output_name='兼容',mode='compatible-quality')
        streams,duration=merge_video.probe(result['path'])
        video=next(x for x in streams if x['codec_type']=='video')
        audio=next(x for x in streams if x['codec_type']=='audio')
        self.assertEqual((video['codec_name'],video['width'],video['height']),('h264',1920,1080))
        self.assertEqual((audio['sample_rate'],audio['channels']),('48000',2))
        self.assertEqual(result['mode'],'compatible-quality')
        self.assertTrue(self.source.exists() and self.second.exists())
        self.assertFalse(list(self.folder.glob('.compatible-*')))

    def test_majority_only_transcodes_outlier(self):
        other=self.folder/'other.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=320x184:r=25:d=0.4','-f','lavfi','-i','sine=duration=0.4','-c:v','libx264','-c:a','aac','-shortest',str(other)],check=True,capture_output=True)
        files=[self.source,other,self.second]
        report=merge_video.merge_compare.compare(files)
        self.assertEqual(report['majorityCount'],2)
        self.assertEqual([r['different'] for r in report['files']],[False,True,False])
        real=merge_video.merge_progress.run;commands=[]
        def run(command,*args,**kwargs):
            commands.append(command);return real(command,*args,**kwargs)
        with patch.object(merge_video.merge_progress,'run',side_effect=run):
            result=merge_video.merge_files(self.root,files,mode='majority')
        self.assertEqual(result['reencoded'],1)
        self.assertEqual(sum('libx264' in cmd for cmd in commands),1)
        self.assertFalse(list(self.folder.glob('.selective-*')))

    def test_symlink_outside_drama_rejected(self):
        outside=self.root/'outside.mp4';shutil.copyfile(self.second,outside)
        self.second.unlink();self.second.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'不在当前剧集目录'):merge_video.merge(self.root,self.folder.name,[{'number':1},{'number':2}])

if __name__=='__main__':unittest.main()
