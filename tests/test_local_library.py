import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
import local_library

class LocalFolderTests(unittest.TestCase):
    def tearDown(self):local_library.LIBRARIES.clear()
    def test_folder_exposes_only_mp4_ids_and_keeps_custom_order(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            for name in ('第10集.mp4','第2集.mp4','note.txt'):(folder/name).write_bytes(b'x')
            (folder/'linked.mp4').symlink_to(folder/'第2集.mp4')
            with patch.object(local_library.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(temp),'')):
                value=local_library.choose_folder()
            self.assertEqual(len(value['files']),2)
            self.assertNotIn(temp,json.dumps(value))
            ids=[f['id'] for f in value['files']][::-1]
            selected=local_library.selected(value['libraryId'],ids)
            self.assertEqual([p.name for p in selected],[f['name'] for f in value['files']][::-1])
            with self.assertRaisesRegex(ValueError,'未授权'):local_library.selected(value['libraryId'],['/etc/passwd'])
            with self.assertRaises(ValueError):local_library.selected(value['libraryId'],ids*2)
    def test_cancel_is_not_an_error(self):
        with patch.object(local_library.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','User canceled. (-128)')):
            self.assertEqual(local_library.choose_folder(),{'cancelled':True})
    def test_native_multiselect_only_registers_chosen_files(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            paths=[folder/f'{n}.mp4' for n in range(3)]
            for path in paths:path.write_bytes(b'x')
            chosen=[str(paths[2]),str(paths[0])]
            with patch.object(local_library.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(chosen),'')) as run:
                value=local_library.choose_files()
            self.assertEqual([f['name'] for f in value['files']],['2.mp4','0.mp4'])
            self.assertEqual(value['selectionMode'],'files')
            self.assertIn('multipleSelectionsAllowed:true',run.call_args.args[0][-1])
            self.assertEqual(value['files'][0]['sourceFolder'],str(folder.resolve()))
    def test_native_multiselect_cancel_and_invalid_file(self):
        with patch.object(local_library.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','(-128)')):
            self.assertEqual(local_library.choose_files(),{'cancelled':True})
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'file.txt';path.write_text('x')
            with patch.object(local_library.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps([str(path)]),'')):
                with self.assertRaises(ValueError):local_library.choose_files()

    def test_append_deduplicates_and_keeps_existing_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'other').mkdir()
            a=root/'a.mp4';b=root/'other'/'b.mp4'
            a.write_bytes(b'x');b.write_bytes(b'x')
            def pick(paths,library=None):
                with patch.object(local_library.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps([str(p) for p in paths]),'')):
                    return local_library.choose_files(library)
            first=pick([a]);second=pick([a,b],first['libraryId'])
            self.assertEqual(second['libraryId'],first['libraryId'])
            self.assertEqual(second['files'][0]['id'],first['files'][0]['id'])
            self.assertEqual(len(second['files']),2)
            self.assertEqual(local_library.selected(second['libraryId'],[f['id'] for f in second['files']]),[a.resolve(),b.resolve()])
