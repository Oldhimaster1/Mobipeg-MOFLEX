"""Exercise recovery with real encoded ranges and a forced assembly failure."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native'))
import MobiPEG_Studio_V15 as studio
from parallel_encode import plan_ranges


class NativeResumeTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and (os.cpu_count() or 1) >= 2,
                         'requires FFmpeg and at least two logical CPUs')
    def test_parallel_size_target_retries_and_preserves_frames(self):
        try:
            encoder = studio.pick_encoder()
        except FileNotFoundError:
            self.skipTest('custom FFmpeg has not been built')
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / 'moving.mkv'
            output = Path(work) / 'target.moflex'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'testsrc2=s=320x240:r=24:d=9', '-f', 'lavfi', '-i',
                'sine=f=880:r=48000:d=9','-c:v','ffv1','-c:a','pcm_s16le',str(source)],check=True)
            args = studio.parser().parse_args(['-i',str(source),'-o',str(output),'--workers','2',
                '--preset','balanced','--resolution','320x240','--max-size-mb','0.85','--resume','--normalize-audio'])
            messages=[]
            studio.encode(args,callback=messages.append)
            self.assertLessEqual(output.stat().st_size,850000)
            self.assertGreater(sum(message.startswith('Range ') for message in messages),2)
            self.assertEqual(messages.count('Measuring audio peak across the selected track...'),1)
            pcm=array('h',subprocess.check_output([str(encoder),'-v','error','-i',str(output),
                '-map','0:a:0','-ac','1','-f','s16le','-']))
            if sys.byteorder=='big':
                pcm.byteswap()
            for start in (48000,5*48000):
                self.assertGreater(max(abs(value) for value in pcm[start:start+1200]),25000)
            self.assertEqual(studio.verified_frame_count(encoder.with_name('ffprobe'+studio.EXE_SUFFIX),output),216)
            args.output=str(Path(work)/'impossible.moflex')
            args.max_size_mb=0.008192
            with self.assertRaisesRegex(ValueError,'too small'):
                studio.encode(args,callback=lambda message: None)
            self.assertFalse(Path(args.output).exists())

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
            boundary = round(plan_ranges(9, '24', workers=2)[1][0] * 48000)
            pulse = f'aevalsrc=sin(2*PI*1000*n/48000)*between(n\\,{boundary-512}\\,{boundary+511}):s=48000:d=9'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=320x240:r=24:d=9', '-f', 'lavfi', '-i',
                            pulse,
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
            pcm = array('h', subprocess.check_output([str(studio.pick_encoder()), '-v', 'error',
                '-xerror', '-i', str(output), '-map', '0:a:0', '-ac', '1', '-f', 's16le', '-']))
            if sys.byteorder == 'big':
                pcm.byteswap()
            self.assertLessEqual(abs(len(pcm)-9*48000), 256)
            # A tone straddles the aligned range boundary. Verify energy on
            # both sides and silence outside the pulse's immediate vicinity.
            self.assertGreater(max(abs(x) for x in pcm[boundary-400:boundary-200]), 15000)
            self.assertGreater(max(abs(x) for x in pcm[boundary+200:boundary+400]), 15000)
            self.assertLess(max(abs(x) for x in pcm[boundary-1000:boundary-700]), 1500)
            self.assertLess(max(abs(x) for x in pcm[boundary+700:boundary+1000]), 1500)
            for offset in (-40,40,9000,-9000):
                args.output=str(Path(work)/f'offset-{offset}.moflex')
                args.audio_offset_ms=offset
                result=studio.encode(args,callback=lambda message: None)
                shifted=array('h',subprocess.check_output([str(studio.pick_encoder()),'-v','error',
                    '-xerror','-i',str(result),'-map','0:a:0','-ac','1','-f','s16le','-']))
                if sys.byteorder=='big':
                    shifted.byteswap()
                self.assertLessEqual(abs(len(shifted)-9*48000),256)
                if abs(offset)==9000:
                    self.assertLess(max(abs(sample) for sample in shifted),10)
                else:
                    active=next(index for index,sample in enumerate(shifted) if abs(sample)>1200)
                    baseline=next(index for index,sample in enumerate(pcm) if abs(sample)>1200)
                    self.assertLessEqual(abs(active-baseline-offset*48),48)


if __name__ == '__main__':
    unittest.main()
