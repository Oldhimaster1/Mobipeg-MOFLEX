#!/usr/bin/env python3
"""Repeatable standard-vs-live muxer parity stress test (2D, stereo, A/V).

Runs independent encoding trials and verifies that every decoded video byte and,
where present, every decoded audio PCM byte matches the legacy indexed muxer.
This tests decoding compatibility, NOT Nintendo hardware or real-time FPS.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import random
import subprocess
import tempfile
import time


spec = importlib.util.spec_from_file_location(
    "plex_live_bridge", pathlib.Path(__file__).with_name("plex_live_bridge.py"))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def cmd_result(cmd, env=None):
    done = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env, timeout=120)
    if done.returncode:
        raise RuntimeError("Command failed: %s\n%s" %
                           (" ".join(str(x) for x in cmd), done.stderr[-2000:].decode("utf8", "replace")))
    return done.stdout


def sample_hash(ffmpeg, filename, typ):
    if typ == "video":
        args = ["-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "yuv420p"]
    else:
        args = ["-map", "0:a:0", "-f", "s16le", "-ar", "44100", "-ac", "2"]
    content = cmd_result([ffmpeg, "-nostdin", "-v", "error", "-i", str(filename)] + args + ["pipe:1"])
    return hashlib.sha256(content).hexdigest(), len(content)


def case_run(ffmpeg, source, destination, mode, fps, qp, seconds, audio, env, clownsec=None):
    base = bridge.ffmpeg_args(ffmpeg, str(source), "", mode, seconds, qp, fps)
    # Remove real-time input pacing for stress testing: test wall time is encoder throughput.
    base.remove("-re")
    base.insert(1, "-y")
    base[-1] = str(destination)
    if not audio:
        base[-3:-3] = ["-an"]
    cmd_result(base, env)
    if clownsec:
        cmd_result([clownsec, str(destination)])
    hashes = {"video": sample_hash(ffmpeg, destination, "video")}
    if audio:
        # Some user inputs are silent; use source probe to decide the stream.
        exists = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(destination),
                                 "-map", "0:a:0?", "-f", "s16le", "pipe:1"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if exists.returncode or not exists.stdout:
            hashes["audio"] = None
        else:
            hashes["audio"] = sample_hash(ffmpeg, destination, "audio")
    return hashes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ffmpeg", required=True)
    p.add_argument("--input", action="append", required=True, help="repeat for more MP4/MOV sources")
    p.add_argument("--cases", type=int, default=40)
    p.add_argument("--seed", type=int, default=20261115)
    p.add_argument("--report", default="live_stress_report.json")
    p.add_argument("--clownsec-demux", help="optional host-built Clownsec parser checker binary")
    args = p.parse_args()
    if not 1 <= args.cases <= 10000:
        p.error("--cases must be 1-10000")
    ffmpeg = str(pathlib.Path(args.ffmpeg).resolve())
    inputs = [pathlib.Path(x).resolve() for x in args.input]
    if not all(x.is_file() for x in inputs):
        p.error("one or more input videos were not found")
    clownsec = str(pathlib.Path(args.clownsec_demux).resolve()) if args.clownsec_demux else None
    rng = random.Random(args.seed)
    rng.shuffle(inputs)
    record = {"source_count": len(inputs), "cases_requested": args.cases,
              "test": "legacy indexed vs incremental MOFLEX decoded byte identity",
              "ffmpeg": ffmpeg, "seed": args.seed, "cases": []}
    env = dict(os.environ, MOBI_SUBME="9", MOBI_SKIP="0")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="moflex-live-qa-") as td:
        td = pathlib.Path(td)
        for i in range(args.cases):
            mode = rng.choice(["2d", "full-sbs", "half-sbs"])
            fps = rng.choice(["10", "15", "24", "30000/1001"])
            qp = rng.choice([12, 16, 20, 24, 30])
            secs = rng.choice([.25, .4, .8, 1.2])
            audio = rng.choice([False, True])
            source = inputs[i % len(inputs)]
            settings = {"case": i + 1, "source": source.name,
                        "mode": mode, "fps": fps, "qp": qp,
                        "seconds": secs, "audio": audio}
            try:
                live = case_run(ffmpeg, source, td / "live.moflex", mode, fps, qp, secs,
                                audio, env, clownsec)
                classic = case_run(ffmpeg, source, td / "classic.moflex", mode, fps, qp, secs,
                                   audio, env)
                if live != classic:
                    raise AssertionError("decoded output differs: live=%r indexed=%r" % (live, classic))
                settings["result"] = "pass"
                settings["decoded_video_bytes"] = live["video"][1]
                if live.get("audio"):
                    settings["decoded_audio_bytes"] = live["audio"][1]
            except Exception as exc:
                settings["result"] = "fail"
                settings["reason"] = str(exc)[-2000:]
            record["cases"].append(settings)
            if (i + 1) % 20 == 0 or i + 1 == args.cases:
                passed = sum(x["result"] == "pass" for x in record["cases"])
                print("%d/%d complete, passed=%d, elapsed=%.1fs" %
                      (i + 1, args.cases, passed, time.monotonic() - started), flush=True)
    record["elapsed_seconds"] = round(time.monotonic() - started, 2)
    record["passed"] = sum(x["result"] == "pass" for x in record["cases"])
    record["failed"] = args.cases - record["passed"]
    pathlib.Path(args.report).write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
    print("FINAL: %d/%d passed; report: %s" %
          (record["passed"], args.cases, args.report), flush=True)
    if record["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
