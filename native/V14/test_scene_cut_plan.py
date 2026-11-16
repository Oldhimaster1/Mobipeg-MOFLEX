#!/usr/bin/env python3
"""Correctness tests for scene-cut detection and paired-eye quantizers."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scene_cut_plan import detect_cuts,protect


class SceneCutTests(unittest.TestCase):
    def fixture(self):
        n=20
        raw=np.zeros((n,24*24*3//2),dtype=np.uint8)
        raw[10:,:24*24]=240
        return raw

    def test_true_same_eye_scene_cut(self):
        data=self.fixture()
        self.assertEqual(detect_cuts(data,24,24,2,38),[10])

    def test_safe_plan_eyes_match(self):
        data=self.fixture()
        new=protect([32]*20,[10],20,2,'safe',data,24,24)
        self.assertEqual(new[10:14],[31]*4)
        self.assertTrue(all(new[i]==new[i+1] for i in range(0,20,2)))

    def test_cut_focus_and_bounds(self):
        data=self.fixture()
        new=protect([12]*20,[10],20,2,'cutfocus',data,24,24)
        self.assertTrue(all(12<=q<=59 for q in new))
        self.assertEqual(len(new),20)

    def test_reject_mismatched_stereo(self):
        with self.assertRaises(ValueError):
            protect([31,32]+[32]*18,[],20,2,'safe')

    def test_reject_odd_frame_cut(self):
        with self.assertRaises(ValueError):
            protect([32]*20,[11],20,2,'safe')

    def test_zero_cut_preserves_safe_plan(self):
        original=[32]*20
        self.assertEqual(protect(original,[],20,2,'safe'),original)


if __name__=='__main__':unittest.main()
