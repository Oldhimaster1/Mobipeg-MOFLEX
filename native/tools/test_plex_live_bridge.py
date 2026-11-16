#!/usr/bin/env python3
"""Host-side regression tests for the custom Plex->MOFLEX HTTP bridge."""
import contextlib
import http.server
import importlib.util
import pathlib
import socket
import threading
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "plex_live_bridge", pathlib.Path(__file__).with_name("plex_live_bridge.py"))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class TestEncoderArguments(unittest.TestCase):
    def build(self, mode, fps="30000/1001"):
        return bridge.ffmpeg_args("/a/ffmpeg", "/a/file.mp4", "", mode, 2, 12, fps)

    def test_2d_output(self):
        cmd = self.build("2d")
        self.assertIn("-mo_live", cmd)
        self.assertEqual(cmd[cmd.index("-mo_layout") + 1], "6")
        self.assertIn("scale=400:240", " ".join(cmd))

    def test_sbs_full(self):
        cmd = self.build("full-sbs")
        self.assertEqual(cmd[cmd.index("-mo_layout") + 1], "4")
        self.assertIn("setsar=1", " ".join(cmd))
        self.assertIn("hstack=inputs=2", " ".join(cmd))

    def test_sbs_half(self):
        cmd = self.build("half-sbs")
        self.assertIn("setsar=2", " ".join(cmd))

    def test_fps(self):
        self.assertIn("fps=15,", " ".join(self.build("2d", "15")))

    def test_audio(self):
        cmd = self.build("2d")
        self.assertEqual(cmd[cmd.index("-mo_audio") + 1], "adpcm")
        self.assertIn("0:a:0?", cmd)

    def test_short_stream(self):
        cmd = self.build("2d")
        self.assertEqual(cmd[-2:], ["moflex", "pipe:1"])
        self.assertEqual(cmd[cmd.index("-t") + 1], "2")

    def test_no_seek_index(self):
        cmd = self.build("2d")
        self.assertEqual(cmd[cmd.index("-mo_live") + 1], "1")

    def test_token_passed_as_header(self):
        cmd = bridge.ffmpeg_args("ffmpeg", "http://example.invalid/part", "abc", "2d", 0, 24)
        self.assertEqual(cmd[cmd.index("-headers") + 1], "X-Plex-Token: abc\r\n")
        self.assertNotIn("abc", cmd[cmd.index("-i") + 1])

    def test_no_time_limit_for_full_movie(self):
        self.assertNotIn("-t", bridge.ffmpeg_args("ffmpeg", "file", "", "2d", 0, 12))


class TestPlexResolver(unittest.TestCase):
    def test_bad_rating_keys(self):
        for bad in ("", "../../etc/passwd", "-1", "1a", "1?foo=bar"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bridge.plex_source("http://127.0.0.1:32400", "token", bad)

    def test_bad_origin(self):
        with self.assertRaises(ValueError):
            bridge.plex_source("file:///etc/passwd", "token", "123")

    def test_parse_plex_item_and_auth(self):
        xml = (b'<MediaContainer><Video><Media><Part key="/library/parts/123/file" />'
               b'</Media></Video></MediaContainer>')
        class Dummy:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, count):
                assert count == 1024 * 1024
                return xml
        with mock.patch.object(bridge.urllib.request, "urlopen", return_value=Dummy()) as opening:
            source = bridge.plex_source("http://localhost:32400", "secret", "123")
        self.assertEqual(source, "http://localhost:32400/library/parts/123/file")
        req = opening.call_args.args[0]
        self.assertEqual(req.get_header("X-plex-token"), "secret")

    def test_reject_missing_part(self):
        class Dummy:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n): return b"<MediaContainer/>"
        with mock.patch.object(bridge.urllib.request, "urlopen", return_value=Dummy()):
            with self.assertRaises(ValueError):
                bridge.plex_source("http://localhost:32400", "token", "123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
