"""Exercise recovery with real encoded ranges and a forced assembly failure."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native'))
import MobiPEG_Studio_V15 as studio


class NativeResumeTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and (os.cpu_count() or 1) >= 2,
                         'requires FFmpeg and at least two logical CPUs')
    def test_verified_ranges_survive_failure_and_corruption(self):
        try:
            studio.pick_encoder()
        except FileNotFoundError:
            self.skipTest('custom FFmpeg has not been built')
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / 'input.mkv'
            output = Path(work) / 'movie.moflex'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=320x240:r=24:d=9', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=48000:duration=9',
                            '-c:v', 'ffv1', '-c:a', 'pcm_s16le', str(source)], check=True)
            args = studio.parser().parse_args(['-i', str(source), '-o', str(output),
                '--preset', 'small', '--resolution', '320x240', '--workers', '2', '--resume'])
            with patch('parallel_encode.join', side_effect=RuntimeError('interrupted before join')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted before join'):
                    studio.encode(args, callback=lambda message: None)
            self.assertFalse(output.exists())
            ranges = sorted(Path(work).glob('.mobipeg-checkpoints/*/part-*.moflex'))
            self.assertEqual(len(ranges), 2)
            with ranges[1].open('r+b') as damaged:
                damaged.seek(8192)
                damaged.write(b'DAMAGED')
            messages = []
            studio.encode(args, callback=messages.append)
            self.assertTrue(output.is_file())
            self.assertIn('Reusing verified range 1/2.', messages)
            self.assertNotIn('Reusing verified range 2/2.', messages)
            self.assertFalse(any(Path(work).glob('.mobipeg-checkpoints/*/part-*')))


if __name__ == '__main__':
    unittest.main()
