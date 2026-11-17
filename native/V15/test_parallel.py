"""No custom FFmpeg needed: binary assembler and timeline planning tests."""
import sys
from pathlib import Path
from fractions import Fraction
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from moflex_join import BLOCK,create_front,inspect,join,set_sync
from parallel_encode import plan_ranges
from MobiPEG_Studio_V15 import estimate_storage

DESCRIPTORS=bytes([3,13,0,0,0,30,0,1,1,144,0,240,1,1,6,4,2,1,0,0,0])


def fixture(path, count=2):
    entries=[(i*30,1+i*1000000,0) for i in range(count)]
    initial=create_front(DESCRIPTORS,1,entries,count*30,count*1000000)
    entries=[(f,t,len(initial)+i*BLOCK) for i,(f,t,_) in enumerate(entries)]
    front=create_front(DESCRIPTORS,1,entries,count*30,count*1000000)
    with open(path,'wb') as file:
        file.write(front)
        for i in range(count):
            block=bytearray(BLOCK)
            set_sync(block,entries[i][1]);block[14:14+len(DESCRIPTORS)]=DESCRIPTORS
            block[14+len(DESCRIPTORS)]=((3+i)&63)<<2
            file.write(block)


class ParallelMovieTests(unittest.TestCase):
    def test_chunk_ranges_do_not_need_chapter_markers(self):
        for fps in (Fraction(24),Fraction(25),Fraction(30),Fraction(48000,1001),Fraction(60000,1001)):
            clips=plan_ranges(3600.0,fps)
            self.assertGreater(len(clips),100)
            previous=0
            for start,duration,coded_frames in clips:
                self.assertAlmostEqual(start,previous/float(fps),places=5)
                self.assertGreater(duration,0)
                self.assertLessEqual(duration,30)
                previous+=coded_frames
                if clips[-1]!=(start,duration,coded_frames):
                    self.assertAlmostEqual(duration*48000/256,round(duration*48000/256),places=6)

    def test_stereo_final_range_has_complete_eye_pairs(self):
        for fps in (Fraction(48),Fraction(60000,1001)):
            clips=plan_ranges(61.037,fps,eyes=2)
            self.assertTrue(all(n%2==0 for _,_,n in clips))

    def test_join_rebases_frames_clocks_seek_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[Path(tmp)/f'part{i}.moflex' for i in range(3)]
            for p in paths:fixture(p)
            out=Path(tmp)/'joined.moflex'
            total=join([(p,60) for p in paths],Fraction(30),out)
            self.assertEqual(total,180)
            parsed=inspect(out,180)
            self.assertEqual(len(parsed.entries),6)
            self.assertEqual(parsed.entries[2][0],60)
            self.assertEqual(parsed.entries[4][0],120)
            self.assertEqual(parsed.entries[2][1],2000001)
            self.assertEqual(parsed.entries[2][2],parsed.front+2*BLOCK)

    def test_reject_mismatched_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.moflex';fixture(path)
            with self.assertRaisesRegex(ValueError,'frame count mismatch'):
                join([(path,59)],Fraction(30),Path(tmp)/'bad.moflex')

    def test_storage_budget_accounts_for_parallel_parts(self):
        a=estimate_storage(3600,'400x240','30','2d',30,True,1)
        b=estimate_storage(3600,'400x240','30','2d',30,True,8)
        self.assertGreater(b['temporary'],a['temporary'])
        self.assertEqual(b['maximum'],a['maximum'])


if __name__=='__main__':unittest.main()
