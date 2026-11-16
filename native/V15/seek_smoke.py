#!/usr/bin/env python3
"""Seek/decode smoke test for V15 MOFLEX, independent of hardware seek QA.

Usage:
  python3 v15_tests/seek_smoke.py --ffmpeg custom/bin/ffmpeg \
    --avatar Avatar_3D_MobiPEG_V15_MotionRefine_EXPERIMENTAL.moflex \
    --anime Anime_FULL_V15_MotionRefine_2D.moflex \
    --yip Yip_FULL_V15_MotionRefine_2D.moflex \
    --report seek_smoke_report.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

POINTS = {
    'avatar': (2.0, 12.0, 25.0, 40.0, 55.0, 72.0, 87.0, 92.5, 95.0, 99.0),
    'anime': (2.0, 15.0, 27.0, 39.0, 51.0, 60.0),
    'yip': (2.0, 12.0, 20.0, 24.0),
}


def run(ffmpeg: Path, videos: dict[str, Path]) -> list[dict]:
    results = []
    for key, locations in POINTS.items():
        if key not in videos:
            continue
        src = videos[key]
        if not src.is_file():
            raise FileNotFoundError(src)
        for seconds in locations:
            proc = subprocess.run([
                str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-xerror',
                '-ss', str(seconds), '-i', str(src), '-map', '0:v:0',
                '-frames:v', '2', '-f', 'framehash', '-'
            ], capture_output=True, timeout=120)
            raw = proc.stdout.decode(errors='replace')
            frames = [line for line in raw.splitlines() if line.startswith('0,')]
            ok = proc.returncode == 0 and len(frames) == 2
            record = {'video': key, 'seek_seconds': seconds, 'exit_code': proc.returncode,
                      'frames_decoded': len(frames), 'pass': ok,
                      'framehash_sha256': hashlib.sha256(proc.stdout).hexdigest(),
                      'error': proc.stderr.decode(errors='replace')[-500:]}
            results.append(record)
            print(('PASS' if ok else 'FAIL'), key, seconds, len(frames), flush=True)
            if not ok:
                raise RuntimeError(f'Failed seek/decode: {record}')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', required=True, type=Path)
    for name in POINTS:
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    results = run(args.ffmpeg.resolve(), {
        key: value.resolve() for key in POINTS if (value := getattr(args, key))
    })
    if args.report:
        args.report.write_text(json.dumps(results, indent=2) + '\n')
    print(f'PASS {len(results)} FFmpeg seek/decode probes. No real 3DS tested.')
