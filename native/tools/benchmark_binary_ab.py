#!/usr/bin/env python3
"""Alternating build A/B benchmark for two custom MobiClip FFmpeg executables.

Verifies the *entire MOFLEX byte stream* is identical for each input and run.
Reports both wall-clock and child CPU user time (Linux/macOS), as the latter
is less sensitive to contention from unrelated processes.
"""
import argparse
import csv
import hashlib
import json
import os
import resource
import statistics
import subprocess
import time
from pathlib import Path


def run(ffmpeg, src, dst, qp, subme, frames):
    env = os.environ.copy()
    env.update(MOBI_SUBME=str(subme), MOBI_SKIP="0", MOBI_FAST_MC="0")
    cmd = [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(src), "-frames:v", str(frames), "-an", "-c:v", "mobiclip",
           "-mobiclip", "1", "-qp", str(qp), "-preset", "medium",
           "-me_method", "hex", "-g", "60", "-f", "moflex", str(dst)]
    cpu_start = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime
    start = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    elapsed = time.perf_counter() - start
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime - cpu_start
    if result.returncode:
        raise RuntimeError(result.stderr)
    return {"wall_s": round(elapsed, 5), "user_cpu_s": round(cpu, 5),
            "fps_wall": round(frames / elapsed, 4),
            "fps_cpu": round(frames / cpu, 4) if cpu > 0 else 0,
            "bytes": dst.stat().st_size,
            "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--input-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--qp", type=int, default=12)
    ap.add_argument("--subme", type=int, default=9)
    args = ap.parse_args()
    sources = sorted(args.input_dir.glob("*.y4m"))
    if not sources:
        ap.error("No Y4M files")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for src in sources:
        for rep in range(args.repeat):
            order = ["baseline", "candidate"] if rep % 2 == 0 else ["candidate", "baseline"]
            for variant in order:
                dst = args.output_dir / f"{src.stem}_{rep}_{variant}.moflex"
                result = run(getattr(args, variant), src, dst,
                             args.qp, args.subme, args.frames)
                row = dict(scene=src.stem, repeat=rep, variant=variant, **result)
                rows.append(row)
                print(f"{src.stem:12s} {variant:10s} rep={rep} "
                      f"wall={result['fps_wall']:.2f} fps "
                      f"CPU={result['fps_cpu']:.2f} fps", flush=True)
    for src in sources:
        hashes = {r["sha256"] for r in rows if r["scene"] == src.stem}
        if len(hashes) != 1:
            raise RuntimeError(f"Byte-for-byte output differed for {src.stem}")
    with (args.output_dir / "runs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    per_scene = {}
    for src in sources:
        per_scene[src.stem] = {
            variant: {metric: round(statistics.median(r[metric] for r in rows
                                                     if r["scene"] == src.stem and
                                                     r["variant"] == variant), 3)
                      for metric in ("fps_wall", "fps_cpu")}
            for variant in ("baseline", "candidate")
        }
    ratios = [per_scene[src.stem]["candidate"]["fps_cpu"] /
              per_scene[src.stem]["baseline"]["fps_cpu"] for src in sources]
    report = dict(runs=len(rows), scenes=len(sources), frames=args.frames,
                  outputs_byte_identical=True, by_scene=per_scene,
                  median_cpu_speedup_pct=round((statistics.median(ratios) - 1) * 100, 3))
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
