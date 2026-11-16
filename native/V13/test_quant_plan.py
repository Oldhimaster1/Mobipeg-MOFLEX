#!/usr/bin/env python3
"""Portable unit tests for stereo-safe adaptive quantizer plans."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from plan_from_raw import make_plan


class TestQuantPlan(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw=Path(self.tmp.name)/'input.yuv'

    def sample(self, pairs=24):
        # Use two spatially different views.  Temporal changes are applied
        # between stereo pairs, never between left and right samples.
        data=np.zeros((pairs*2,24*24*3//2),dtype=np.uint8)
        for i in range(pairs):
            for eye in range(2):
                p=data[2*i+eye,:24*24].reshape(24,24)
                if i%5==0:p[:]=i*7+eye*18
                elif i%5==1:p[::2,::2]=210-i*3
                else:p[:]=(i*7+eye*18)%255
        self.raw.write_bytes(data.tobytes())

    def test_interleaved_eyes_share_quantizer(self):
        self.sample()
        for m in ('balanced','motion','detail'):
            q=make_plan(self.raw,24,24,32,2,2,m,1)
            self.assertEqual(len(q),48)
            self.assertTrue(all(q[i]==q[i+1] for i in range(0,48,2)))
            self.assertTrue(all(12<=z<=59 for z in q))

    def test_unbalanced_file_rejected(self):
        self.raw.write_bytes(b'not raw video')
        with self.assertRaises(ValueError):
            make_plan(self.raw,24,24,32,2,1,'motion',1)

    def test_no_frame_rejected(self):
        self.raw.write_bytes(b'')
        with self.assertRaises(ValueError):
            make_plan(self.raw,24,24,32,2,1,'motion',1)

    def test_quantizer_bounds(self):
        self.sample()
        for base in (12,59):
            q=make_plan(self.raw,24,24,base,2,2,'balanced',1)
            self.assertTrue(all(12<=z<=59 for z in q))

    def test_two_dimensional_mode(self):
        self.sample()
        q=make_plan(self.raw,24,24,32,1,1,'detail',2)
        self.assertEqual(len(q),48)


if __name__=='__main__':unittest.main()
