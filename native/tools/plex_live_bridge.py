#!/usr/bin/env python3
"""Experimental live MOFLEX HTTP bridge for the CUSTOM MobiPEG encoder.

Plex supplies the source. This service streams incremental MOFLEX bytes over
HTTP/1.1 chunked transfer; it does not generate a complete indexed .moflex.
The currently released Big Top 3DS httpfile client requires a known length and
Range requests, so it CANNOT play this endpoint without client changes.
"""

import argparse
import fractions
import http.server
import json
import os
import pathlib
import re
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


DEFAULT_FPS = "30000/1001"
SCALE = ("scale=400:240:force_original_aspect_ratio=decrease:"
         "force_divisible_by=2:in_range=auto:out_range=tv:flags=lanczos,"
         "pad=400:240:(ow-iw)/2:(oh-ih)/2,setsar=1")


def plex_source(base, token, rating_key):
    """Resolve a Plex metadata rating key to its first playable Part URL."""
    if not re.fullmatch(r"[0-9]+", rating_key):
        raise ValueError("Plex rating key must contain digits only")
    base = base.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Plex base URL must be an absolute http(s) URL")
    url = base + "/library/metadata/" + rating_key
    req = urllib.request.Request(url, headers={"X-Plex-Token": token})
    with urllib.request.urlopen(req, timeout=15) as response:
        xml = response.read(1024 * 1024)
    root = ET.fromstring(xml)
    part = root.find(".//Media/Part")
    if part is None or not part.get("key", "").startswith("/"):
        raise ValueError("Plex item has no accessible direct-play Part")
    return base + part.attrib["key"]


def ffmpeg_args(ffmpeg, source, token, mode, seconds, qp, fps=DEFAULT_FPS):
    cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error",
           "-re"]
    if token:
        # Header avoids putting a Plex token in a URL or in request logs.
        cmd += ["-headers", "X-Plex-Token: " + token + "\r\n"]
    cmd += ["-i", source]
    if mode == "2d":
        cmd += ["-map", "0:v:0", "-vf", "fps=" + fps + "," + SCALE + ",format=yuv420p"]
        layout = "6"
    else:
        sar = "2" if mode == "half-sbs" else "1"
        eye = "setsar=" + sar + "," + SCALE
        filt = ("[0:v:0]fps=" + fps + ",split=2[l][r];"
                "[l]crop=iw/2:ih:0:0," + eye + "[lo];"
                "[r]crop=iw/2:ih:iw/2:0," + eye + "[ro];"
                "[lo][ro]hstack=inputs=2,format=yuv420p[v]")
        cmd += ["-filter_complex", filt, "-map", "[v]"]
        layout = "4"
    cmd += ["-map", "0:a:0?", "-c:v", "mobiclip", "-mobiclip", "1",
            "-qp", str(qp), "-preset", "medium", "-me_method", "hex",
            "-g", "60", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
            "-mo_audio", "adpcm", "-mo_layout", layout, "-mo_live", "1"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-f", "moflex", "pipe:1"]
    return cmd


class LiveServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(args):
    ffmpeg = pathlib.Path(args.ffmpeg).expanduser().resolve()
    if not ffmpeg.is_file():
        raise ValueError("Our custom ffmpeg binary does not exist: " + str(ffmpeg))
    token = os.environ.get("PLEX_TOKEN", "").strip()
    if args.rating_key:
        if not token:
            raise ValueError("Set PLEX_TOKEN in the environment for Plex access")
        source = plex_source(args.plex_base, token, args.rating_key)
    else:
        source = str(pathlib.Path(args.source).expanduser().resolve())
        token = ""
        if not pathlib.Path(source).is_file():
            raise ValueError("Source file not found: " + source)
    cmd = ffmpeg_args(ffmpeg, source, token, args.mode, args.seconds, args.qp, args.fps)
    semaphore = threading.BoundedSemaphore(1)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            if path == "/health":
                blob = json.dumps({"service": "mobipeg-live-preview", "mode": args.mode,
                                   "indexed": False, "bigtop_legacy_compatible": False}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                return
            if path != "/live.moflex":
                self.send_error(404)
                return
            if not semaphore.acquire(blocking=False):
                self.send_error(503, "Another encode is already in progress")
                return
            try:
                self.stream()
            finally:
                semaphore.release()

        def stream(self):
            env = dict(os.environ, MOBI_SUBME=str(args.subme), MOBI_SKIP=str(args.skip))
            with tempfile.TemporaryFile() as errors:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors,
                                        stdin=subprocess.DEVNULL, env=env)
                sent = 0
                try:
                    # Confirm the encoder emitted something before returning HTTP 200.
                    # FFmpeg failures (missing codecs, invalid input) become a clear 502.
                    first = proc.stdout.read(4096)
                    if not first:
                        proc.wait()
                        self.send_error(502, "MobiPEG encoder failed before streaming")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-MobiPEG-Live", "1")
                    self.end_headers()
                    self.wfile.write(("%x\r\n" % len(first)).encode("ascii"))
                    self.wfile.write(first + b"\r\n")
                    self.wfile.flush()
                    sent += len(first)
                    while True:
                        block = proc.stdout.read(4096)
                        if not block:
                            break
                        self.wfile.write(("%x\r\n" % len(block)).encode("ascii"))
                        self.wfile.write(block + b"\r\n")
                        self.wfile.flush()
                        sent += len(block)
                    proc.wait()
                    # A complete chunked transfer only if ffmpeg succeeded.
                    if proc.returncode == 0:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    else:
                        self.close_connection = True
                except (BrokenPipeError, ConnectionResetError, OSError):
                    self.close_connection = True
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                    proc.stdout.close()
                    print("Encoded request ended: %d bytes, ffmpeg exit %s" %
                          (sent, proc.returncode), flush=True)
                    if proc.returncode not in (0, -15):
                        errors.seek(0)
                        # Encoder stderr can contain internal paths, but no URL token.
                        tail = errors.read()[-3000:].decode("utf-8", "replace")
                        print("Encoder diagnostic:\n" + tail, flush=True)

        def log_message(self, fmt, *v):
            # Don't log user-supplied query strings or a Plex source URL.
            print("Request from %s: %s" % (self.client_address[0], fmt % v), flush=True)

    srv = LiveServer((args.host, args.port), Handler)
    print("Custom MobiPEG live bridge: http://%s:%d/live.moflex" %
          (args.host, args.port), flush=True)
    print("Standalone incremental HTTP transport. Existing Clownsec Big Top"
          " requires HEAD+Range and cannot use this endpoint yet.", flush=True)
    try:
        srv.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--source", help="Local MP4/MKV input for testing")
    sources.add_argument("--rating-key", help="Plex library item ratingKey (digits)")
    parser.add_argument("--plex-base", default="http://127.0.0.1:32400")
    parser.add_argument("--ffmpeg", default=str(pathlib.Path(__file__).resolve().parents[1]
                                                / "local/bin/ffmpeg"))
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 by default. Binding LAN addresses exposes unencrypted video.")
    parser.add_argument("--port", type=int, default=32550)
    parser.add_argument("--mode", choices=["2d", "full-sbs", "half-sbs"], default="2d")
    parser.add_argument("--qp", type=int, default=12)
    parser.add_argument("--fps", default=DEFAULT_FPS,
                        help="Output frames per second (e.g. 15 or 30000/1001). Lower rates reduce CPU load.")
    parser.add_argument("--subme", type=int, choices=range(1, 12), default=9,
                        help="Native motion-search subpixel precision; default 9 preserves quality")
    parser.add_argument("--skip", type=int, default=0,
                        help="Native skip threshold; default 0 preserves tested quality")
    parser.add_argument("--seconds", type=float, default=0,
                        help="Limit test duration, 0 means full input")
    args = parser.parse_args()
    if not 0 <= args.qp <= 51:
        parser.error("--qp must be 0–51")
    try:
        fps = fractions.Fraction(args.fps)
        if not fractions.Fraction(1, 1) <= fps <= fractions.Fraction(60, 1):
            raise ValueError()
    except (ValueError, ZeroDivisionError):
        parser.error("--fps must be between 1 and 60 (integer or rational)")
    if not 0 <= args.skip <= 4096:
        parser.error("--skip must be 0–4096")
    try:
        serve(args)
    except (OSError, ValueError, ET.ParseError) as exc:
        parser.exit(2, "MobiPEG live bridge: %s\n" % exc)


if __name__ == "__main__":
    main()
