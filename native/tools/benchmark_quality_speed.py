#!/usr/bin/env python3
"""Measure real FFmpeg MobiClip speed, PSNR and file sizes by search depth.

Inputs are fixed-resolution Y4M files so scaling/decoding does not skew speed.
PSNR compares the decoded MOFLEX to each original, frame-aligned Y4M stream.
"""
import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ffmpeg", type=Path, required=True)
    ap.add_argument("--input-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--qp", type=int, default=12)
    ap.add_argument("--subme", nargs="+", type=int, default=[2, 5, 7, 9])
    ap.add_argument("--skip", type=int, default=0,
                    help="MobiClip static-area threshold (0 disables residual skip)")
    args = ap.parse_args()
    inputs = sorted(args.input_dir.glob("*.y4m"))
    if not inputs:
        ap.error("No Y4M inputs")
    args.output_dir.mkdir(exist_ok=True, parents=True)
    rows = []
    for source in inputs:
        for rep in range(args.repeat):
            levels = args.subme if not rep % 2 else list(reversed(args.subme))
            for level in levels:
                dst = args.output_dir / (f"{source.stem}_subme{level}"
                                         f"_skip{args.skip}_r{rep}.moflex")
                env = os.environ.copy()
                env.update(MOBI_SUBME=str(level), MOBI_SKIP=str(args.skip),
                           MOBI_FAST_MC="0")
                cmd = [str(args.ffmpeg), "-hide_banner", "-nostdin", "-v", "error", "-y",
                       "-i", str(source), "-frames:v", str(args.frames), "-an",
                       "-c:v", "mobiclip", "-mobiclip", "1", "-qp", str(args.qp),
                       "-preset", "medium", "-me_method", "hex", "-g", "60",
                       "-f", "moflex", str(dst)]
                begin = time.perf_counter()
                output = subprocess.run(cmd, capture_output=True, text=True, env=env)
                seconds = time.perf_counter() - begin
                if output.returncode:
                    raise RuntimeError(output.stderr)
                check = subprocess.run(
                    [str(args.ffmpeg), "-hide_banner", "-nostdin", "-v", "info",
                     "-i", str(dst), "-i", str(source), "-filter_complex",
                     "[0:v:0][1:v:0]psnr", "-frames:v", str(args.frames),
                     "-f", "null", "-"], capture_output=True, text=True)
                if check.returncode:
                    raise RuntimeError(check.stderr)
                match = re.search(r"PSNR y:([0-9.]+) u:([0-9.]+) v:([0-9.]+) "
                                  r"average:([0-9.]+)", check.stderr)
                if not match:
                    raise RuntimeError(f"Could not read PSNR: {check.stderr[-800:]}")
                row = dict(source=source.name, subme=level, skip=args.skip, repeat=rep,
                           seconds=round(seconds, 5), fps=round(args.frames / seconds, 4),
                           bytes=dst.stat().st_size,
                           psnr_y=float(match[1]), psnr_u=float(match[2]),
                           psnr_v=float(match[3]), psnr_average=float(match[4]))
                rows.append(row)
                print(f"{source.stem:16} subme={level} rep={rep}: "
                      f"{row['fps']:6.2f} fps, {row['psnr_average']:.3f} dB, "
                      f"{row['bytes'] / 1048576:.2f} MiB", flush=True)
    with (args.output_dir / "runs.csv").open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    summary = []
    for source in inputs:
        for level in args.subme:
            selected = [r for r in rows if r["source"] == source.name and
                        r["subme"] == level]
            summary.append(dict(source=source.stem, subme=level, skip=args.skip,
                                median_fps=round(statistics.median(r["fps"] for r in selected), 3),
                                mean_psnr=round(statistics.mean(r["psnr_average"]
                                                                 for r in selected), 4),
                                size_bytes=selected[0]["bytes"]))
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
