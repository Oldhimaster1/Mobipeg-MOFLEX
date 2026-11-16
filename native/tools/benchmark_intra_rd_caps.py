#!/usr/bin/env python3
"""Measure I4x4 RD-search budgets using real encode, decoded PSNR and SHA256.

Use already normalized 400x240 Y4M clips. Cap 0 is the unmodified subme9
quality reference. Alternate cap order per repetition to limit run-order bias.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import statistics
import subprocess
import time
from pathlib import Path


def check(argv, *, env=None):
    p = subprocess.run([str(x) for x in argv], env=env, text=True,
                       capture_output=True)
    if p.returncode:
        raise RuntimeError(f"Command failed: {argv!r}\n{p.stderr[-2500:]}")
    return p.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ffmpeg', type=Path, required=True)
    ap.add_argument('--input-dir', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--caps', nargs='+', type=int, default=[0, 1, 2, 3, 4, 6, 9])
    ap.add_argument('--repetitions', type=int, default=2)
    ap.add_argument('--frames', type=int, default=120)
    ap.add_argument('--qp', type=int, default=12)
    ap.add_argument('--subme', type=int, default=9)
    args = ap.parse_args()
    if not args.ffmpeg.is_file() or args.repetitions < 1 or args.frames < 2:
        ap.error('Require real FFmpeg, positive repeats and at least two frames')
    if not args.caps or any(x < 0 or x > 9 for x in args.caps):
        ap.error('caps must be integers in 0..9')
    clips = sorted(args.input_dir.glob('*.y4m'))
    if not clips:
        ap.error('No Y4M inputs')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for source in clips:
        for rep in range(args.repetitions):
            caps = args.caps if not rep % 2 else list(reversed(args.caps))
            for cap in caps:
                dest = args.output_dir / f'{source.stem}_cap{cap}_r{rep}.moflex'
                env = {**os.environ, 'MOBI_INTRA_RD_CAP': str(cap),
                       'MOBI_SUBME': str(args.subme), 'MOBI_SKIP': '0',
                       'MOBI_PROFILE': '0', 'MOBI_FAST_MC': '0', 'MOBI_FAST_SAD': '0'}
                cmd = [args.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error',
                       '-y', '-i', source, '-frames:v', str(args.frames), '-an',
                       '-c:v', 'mobiclip', '-mobiclip', '1', '-qp', str(args.qp),
                       '-preset', 'medium', '-me_method', 'hex', '-g', '60',
                       '-mo_layout', '6', '-f', 'moflex', dest]
                start = time.perf_counter()
                check(cmd, env=env)
                elapsed = time.perf_counter() - start
                stderr = check([args.ffmpeg, '-hide_banner', '-nostdin', '-v', 'info',
                                '-i', dest, '-i', source,
                                '-filter_complex', '[0:v][1:v]psnr',
                                '-frames:v', str(args.frames), '-f', 'null', '-'])
                psnr = re.search(r'PSNR y:([0-9.]+) u:([0-9.]+) v:([0-9.]+) '
                                 r'average:([0-9.]+)', stderr)
                if not psnr:
                    raise RuntimeError(f'No decoded PSNR: {stderr[-1200:]}')
                row = dict(source=source.stem, cap=cap, rep=rep,
                           fps=round(args.frames / elapsed, 3),
                           seconds=round(elapsed, 4),
                           psnr=round(float(psnr.group(4)), 5),
                           bytes=dest.stat().st_size,
                           sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
                rows.append(row)
                print(f'{source.stem:12s} cap={cap:<2d} rep={rep} '
                      f'{row["fps"]:.2f} fps PSNR={row["psnr"]:.4f} '
                      f'bytes={row["bytes"]}', flush=True)
    with (args.output_dir / 'runs.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for source in clips:
        baseline = next(x for x in rows if x['source'] == source.stem and x['cap'] == 0)
        for cap in args.caps:
            items = [x for x in rows if x['source'] == source.stem and x['cap'] == cap]
            summary.append(dict(source=source.stem, cap=cap,
                                median_fps=round(statistics.median(x['fps'] for x in items), 3),
                                psnr=round(statistics.mean(x['psnr'] for x in items), 5),
                                psnr_delta_db=round(statistics.mean(x['psnr'] for x in items)-baseline['psnr'], 5),
                                bytes=items[0]['bytes'],
                                byte_identical_to_cap0=all(x['sha256'] == baseline['sha256'] for x in items)))
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('SUMMARY:')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
