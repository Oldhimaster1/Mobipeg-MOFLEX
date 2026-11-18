"""Real, synthetic MOFLEX structural fixtures. No patched encoder or private videos needed."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

NATIVE=Path(__file__).resolve().parents[1]/'native'
sys.path.insert(0,str(NATIVE))
import moflex_join
import moflex_check


def fixture(path, *, width=400, height=224, fps=24, layout=6, frames=24,
            first_offset=4096, subtitle=False):
    video=struct.pack('>IHHH',fps,1,width,height)+b'\x00\x00'+bytes([layout])
    descriptors=b'\x03\x0d'+video+b'\x04\x02\x01\x00\x00\x00'
    index=moflex_join.create_front(descriptors,1,[(0,1,first_offset)],frames,
                                   frames*1000000//fps)
    media=bytearray(4096)
    moflex_join.set_sync(media,1)
    media[14:14+len(descriptors)]=descriptors
    data=index+bytes(media)
    if subtitle:
        body=b'ENG\x00'+b'1\n00:00:00,000 --> 00:00:00,500\nHello\n'
        data+=b'SUB1'+struct.pack('<I',len(body))+body
        data+=struct.pack('<Q8s',len(index)+len(media),b'CSXTRA01')
    path.write_bytes(data)
    return path


class MoflexPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='moflex-check-test-')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'synthetic.moflex'

    def test_regular_movie_index_and_geometry(self):
        fixture(self.path)
        result=moflex_check.evaluate(self.path)
        self.assertEqual(result['status'],'pass',result)
        self.assertEqual(result['video']['eye_width'],400)
        self.assertEqual(result['video']['frames'],24)
        self.assertEqual(result['seek_index']['entries'],1)

    def test_super_trailer_is_checked_without_stripping_or_copying_media(self):
        fixture(self.path,subtitle=True)
        result=moflex_check.evaluate(self.path)
        self.assertEqual(result['status'],'pass',result)
        self.assertTrue(result['extras']['has_super_moflex'])
        self.assertEqual(result['extras']['subtitles'],1)
        self.assertIn('EXTRA_PLAYER_REQUIRED',{issue['code'] for issue in result['checks']})

    def test_out_of_range_index_fails_instead_of_claiming_compatibility(self):
        fixture(self.path,first_offset=8192)
        result=moflex_check.evaluate(self.path)
        self.assertEqual(result['status'],'fail',result)
        self.assertIn('MOFLEX_STRUCTURE',{issue['code'] for issue in result['checks']})

    def test_experimental_fps_and_size_carry_warnings(self):
        fixture(self.path,width=960,height=480,fps=60)
        result=moflex_check.evaluate(self.path)
        self.assertEqual(result['status'],'warning',result)
        codes={issue['code'] for issue in result['checks']}
        self.assertIn('EXPERIMENTAL_RESOLUTION',codes)
        self.assertIn('EXPERIMENTAL_FRAME_RATE',codes)

    def test_legacy_long_duration_warning(self):
        fixture(self.path,frames=120000)
        result=moflex_check.evaluate(self.path)
        self.assertEqual(result['status'],'warning',result)
        self.assertIn('LONG_MOVIE_SEEKING',{issue['code'] for issue in result['checks']})

    def test_command_line_json_and_exit_codes(self):
        fixture(self.path)
        run=subprocess.run([sys.executable,str(NATIVE/'moflex_check.py'),str(self.path),'--json'],
                           capture_output=True,text=True,check=False)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'],'pass')
        self.path.write_bytes(b'not a real moflex')
        fail=subprocess.run([sys.executable,str(NATIVE/'moflex_check.py'),str(self.path),'--json'],
                            capture_output=True,text=True,check=False)
        self.assertEqual(fail.returncode,1,fail.stderr)
        self.assertEqual(json.loads(fail.stdout)['status'],'fail')


if __name__=='__main__':
    unittest.main()
