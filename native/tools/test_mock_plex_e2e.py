#!/usr/bin/env python3
"""Full local integration: fake Plex metadata + authenticated HTTP part + live MOFLEX.

Uses a supplied MP4 and compiled custom FFmpeg; never needs an actual Plex token.
"""
import argparse
import http.server
import os
import pathlib
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check(args):
    video = pathlib.Path(args.input).resolve().read_bytes()
    token = "testing-only-not-a-real-token"
    requests = []

    class Plex(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("X-Plex-Token")))
            if self.headers.get("X-Plex-Token") != token:
                self.send_error(401)
                return
            if self.path == "/library/metadata/1234":
                body = (b'<MediaContainer><Video><Media><Part '
                        b'key="/library/parts/1234/file" /></Media></Video></MediaContainer>')
                content_type = "application/xml"
            elif self.path == "/library/parts/1234/file":
                body = video
                content_type = "video/mp4"
            else:
                self.send_error(404)
                return
            hdr = self.headers.get("Range", "")
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", hdr)
            if match and self.path.endswith("/file"):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else len(body) - 1
                end = min(end, len(body) - 1)
                if start >= len(body):
                    self.send_error(416)
                    return
                original_length = len(body)
                body = body[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, original_length))
            else:
                self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    plex_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Plex)
    thread = threading.Thread(target=plex_server.serve_forever, daemon=True)
    thread.start()
    server_port = free_port()
    script = pathlib.Path(__file__).with_name("plex_live_bridge.py")
    env = dict(os.environ, PLEX_TOKEN=token)
    with tempfile.TemporaryDirectory(prefix="plex-e2e-") as tempdir:
        result = pathlib.Path(tempdir) / "stream.moflex"
        bridge = subprocess.Popen(["python3", str(script), "--ffmpeg", str(pathlib.Path(args.ffmpeg).resolve()),
                                   "--rating-key", "1234", "--plex-base",
                                   "http://127.0.0.1:%d" % plex_server.server_port,
                                   "--seconds", "0.6", "--port", str(server_port)],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raised = None
        try:
            url = "http://127.0.0.1:%d/live.moflex" % server_port
            for _ in range(40):
                try:
                    with urllib.request.urlopen(url.replace("/live.moflex", "/health"), timeout=.5) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(.1)
            else:
                raise AssertionError("bridge failed to start")
            with urllib.request.urlopen(url, timeout=20) as response:
                assert response.status == 200
                assert response.headers.get("X-MobiPEG-Live") == "1"
                result.write_bytes(response.read())
            assert result.stat().st_size > 4096, "incomplete output"
            decoder = subprocess.run([str(pathlib.Path(args.ffmpeg).resolve()), "-nostdin", "-v", "error",
                                      "-xerror", "-i", str(result), "-map", "0:v:0", "-f", "null", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            assert decoder.returncode == 0, decoder.stderr.decode("utf8", "replace")
            assert ("/library/metadata/1234", token) in requests
            assert ("/library/parts/1234/file", token) in requests
            print("PASS: mock Plex auth + metadata + Part HTTP + live stream + video decode")
            print("MOFLEX bytes: %d; authenticated Plex requests: %d" %
                  (result.stat().st_size, len(requests)))
        except Exception as exc:
            raised = exc
        finally:
            bridge.terminate()
            try:
                out, err = bridge.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                bridge.kill()
                out, err = bridge.communicate()
            plex_server.shutdown()
            plex_server.server_close()
            if raised is not None:
                raise AssertionError("Bridge failed: %s\nstdout:\n%s\nstderr:\n%s\nPlex requests: %s" %
                                     (raised, out.decode("utf8", "replace")[-4000:],
                                      err.decode("utf8", "replace")[-2000:], requests)) from raised


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--input", required=True)
    check(parser.parse_args())
