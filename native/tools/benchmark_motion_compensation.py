#!/usr/bin/env python3
"""Reproducible, same-binary A/B test of Mobiclip motion compensation.

Inputs must already be preprocessed identically (e.g. 400x240 yuv420p Y4M).
MOBI_FAST_MC=0 uses the original per-4x4 predictor; =1 enables the optional
whole-block predictor when all 16 cells share a motion vector and reference.
The benchmark deliberately excludes decode/scale and tests byte identity.
"""
import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import time
from pathlib import Path


def encode(ffmpeg, source, dest, enabled, qp, subme, skip, frames, switch):
    env = os.environ.copy()
    env.update(MOBI_FAST_MC="0", MOBI_FAST_SAD="0", MOBI_SUBME=str(subme),
               MOBI_SKIP=str(skip))
    env[switch] = str(int(enabled))
    command = [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error",
               "-y", "-i", str(source), "-frames:v", str(frames), "-an",
               "-c:v", "mobiclip", "-mobiclip", "1", "-qp", str(qp),
               "-preset", "medium", "-me_method", "hex", "-g", "60",
               "-f", "moflex", str(dest)]
    start = time.perf_counter()
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    if result.returncode:
        raise RuntimeError(f"{source.name} fast={enabled}: {result.stderr}")
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    return dict(seconds=elapsed, fps=frames / elapsed,
                bytes=dest.stat().st_size, sha256=digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--qp", type=int, default=12)
    parser.add_argument("--subme", type=int, default=9)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--switch", choices=["MOBI_FAST_MC", "MOBI_FAST_SAD"],
                        default="MOBI_FAST_MC")
    args = parser.parse_args()
    sources = sorted(args.input_dir.glob("*.y4m"))
    if not sources:
        parser.error(f"No .y4m test inputs in {args.input_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for source in sources:
        for rep in range(args.repeat):
            # Alternate ordering to avoid attributing warmer caches to the
            # modified predictor. Both modes use identical executable/flags.
            order = (0, 1) if rep % 2 == 0 else (1, 0)
            for mode in order:
                dest = args.output_dir / f"{source.stem}_r{rep}_mc{mode}.moflex"
                data = encode(args.ffmpeg, source, dest, mode, args.qp,
                              args.subme, args.skip, args.frames, args.switch)
                row = dict(source=source.name, repeat=rep, fast_mc=mode, **data)
                rows.append(row)
                print(f"{source.name:22s} rep={rep} fast={mode} "
                      f"fps={data['fps']:7.2f} bytes={data['bytes']}", flush=True)
    for source in sources:
        variants = [r for r in rows if r["source"] == source.name]
        hashes = {r["sha256"] for r in variants}
        if len(hashes) != 1:
            raise RuntimeError(f"BITSTREAM DIFFERENCE: {source.name}: {hashes}")
    with (args.output_dir / "runs.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    rates = {mode: statistics.median(r["fps"] for r in rows
                                     if r["fast_mc"] == mode) for mode in (0, 1)}
    by_source = {}
    for source in sources:
        by_source[source.stem] = {
            str(mode): round(statistics.median(r["fps"] for r in rows
                                               if r["fast_mc"] == mode and
                                               r["source"] == source.name), 3)
            for mode in (0, 1)
        }
    summary = {"switch": args.switch, "source_count": len(sources), "runs": len(rows),
               "all_outputs_byte_identical": True, "qp": args.qp,
               "subme": args.subme, "skip": args.skip, "frames": args.frames,
               "median_fps_original": round(rates[0], 3),
               "median_fps_fast": round(rates[1], 3),
               "median_speedup_percent": round((rates[1] / rates[0] - 1) * 100, 3),
               "by_source_fps": by_source}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
