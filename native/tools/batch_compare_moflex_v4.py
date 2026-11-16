#!/usr/bin/env python3
"""Full-length, reproducible quality-vs-turbo A/B test for nine user clips.

No footage is published; both encoder modes retain their input's audio.
The reference remains QP12/subme9/skip0. Turbo applies the SATD I4x4
refinement shortlist, which is a *lossy* search-quality tradeoff.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from mobipeg_parallel_v4 import normalized_video


CLIPS = [
    ('theosbasement69', 'Video by theosbasement69.mp4'),
    ('heart', '＜3 [7289657491514821931].mp4'),
    ('flawisas', 'Video_by_flawisas_Dec0DGGxuw0.mp4'),
    ('nathanleeallen', 'Video by nathanleeallen.mp4'),
    ('stonelifts', 'Video by stonelifts.mp4'),
    ('officialjadenwilliams', 'Video by officialjadenwilliams.mp4'),
    ('uhidkuh', 'Video by uhidkuh.mp4'),
    ('sixtwo2', 'Video by sixtwo2.mp4'),
    ('yippee_jazz', "NA - YIPPEE but it's JAZZ (tbh creature)(1).mp4"),
]


def checked(argv, *, env=None):
    proc = subprocess.run([str(x) for x in argv], capture_output=True,
                          text=True, errors='replace', env=env)
    if proc.returncode:
        raise RuntimeError(f'Failed: {argv}\n{proc.stderr[-4000:]}\n{proc.stdout[-2000:]}')
    return proc.stdout, proc.stderr


def probe_streams(ffprobe, source):
    out, _ = checked([ffprobe, '-v', 'error', '-show_entries',
                      'stream=codec_name,codec_type,sample_rate,channels',
                      '-of', 'json', source])
    return json.loads(out)['streams']


def quality_score(ffmpeg, reference, encoded):
    _, stderr = checked([ffmpeg, '-nostdin', '-hide_banner', '-v', 'info',
                         '-i', reference, '-i', encoded,
                         '-filter_complex', '[0:v:0][1:v:0]psnr',
                         '-an', '-f', 'null', '-'])
    m = re.search(r'PSNR y:([0-9.inf]+) u:([0-9.inf]+) v:([0-9.inf]+) average:([0-9.inf]+)', stderr)
    if not m:
        raise RuntimeError(f'PSNR filter failed: {stderr[-2000:]}')
    return round(float(m.group(4)), 5)


def run_conversion(args, slug, path, mode):
    target = args.output / mode / f'{slug}_{mode}.moflex'
    report = args.output / 'logs' / f'{slug}_{mode}.json'
    stdout_log = args.output / 'logs' / f'{slug}_{mode}.log'
    target.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    if args.resume and target.is_file() and report.is_file():
        row = json.loads(report.read_text())
        if row.get('validated_full_decode') and row.get('bytes') == target.stat().st_size:
            print(f'  reused verified {mode} output: {target.name}', flush=True)
            return target, row
    env = {**os.environ, 'MOBI_INTRA_RD_CAP': '0' if mode == 'quality' else '3',
           'MOBI_INTRA_RD_POLICY': '1', 'MOBI_PROFILE': '0',
           'MOBI_FAST_MC': '0', 'MOBI_FAST_SAD': '0'}
    argv = [sys.executable, args.parallel, path, target,
            '--ffmpeg', args.ffmpeg, '--ffprobe', args.ffprobe,
            '--jobs', str(args.jobs), '--chunk-frames', '60',
            '--seam-mode', 'gop', '--gop', '60', '--fps', '30000/1001',
            '--qp', '12', '--subme', '9', '--skip', '0',
            '--report', report, '--overwrite']
    stdout, stderr = checked(argv, env=env)
    stdout_log.write_text(stdout + ('\nSTDERR:\n' + stderr if stderr else ''))
    row = json.loads(report.read_text())
    if not row.get('validated_full_decode'):
        raise RuntimeError(f'{slug} {mode} has no successful full-decode check')
    return target, row


def produce_charts(rows, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    rows = sorted(rows, key=lambda x: x['original_name'].lower())
    labels = [r['slug'] for r in rows]
    pos = np.arange(len(rows))
    fig, axs = plt.subplots(2, 2, figsize=(17, 12), layout='constrained')
    fig.patch.set_facecolor('#101827')
    blue, green, amber = '#60a5fa', '#34d399', '#fbbf24'
    for a in axs.flat:
        a.set_facecolor('#182335')
        a.tick_params(colors='#dbeafe', labelsize=10)
        a.xaxis.label.set_color('#dbeafe')
        a.yaxis.label.set_color('#dbeafe')
        a.title.set_color('#f8fafc')
        a.grid(axis='x', alpha=0.14, color='#dbeafe')
        a.set_axisbelow(True)
        for sp in a.spines.values(): sp.set_color('#334155')
    a = axs[0, 0]
    a.barh(pos - .18, [r['quality_fps_total'] for r in rows], height=.35, color=blue, label='Quality')
    a.barh(pos + .18, [r['turbo_fps_total'] for r in rows], height=.35, color=green, label='Turbo')
    a.set_yticks(pos, labels); a.invert_yaxis()
    a.set_title('Full conversion throughput (includes verification)')
    a.set_xlabel('Frames per second'); a.legend(facecolor='#182335', labelcolor='white')
    a = axs[0, 1]
    a.barh(pos - .18, [r['quality_fps_encode'] for r in rows], height=.35, color=blue)
    a.barh(pos + .18, [r['turbo_fps_encode'] for r in rows], height=.35, color=green)
    a.set_yticks(pos, labels); a.invert_yaxis()
    a.set_title('Encoder stage only (eight workers)')
    a.set_xlabel('Frames per second')
    a = axs[1, 0]
    changes = [r['size_delta_percent'] for r in rows]
    a.barh(pos, changes, color=[green if v <= 0 else amber for v in changes])
    a.axvline(0, color='#f8fafc', alpha=.5)
    a.set_yticks(pos, labels); a.invert_yaxis()
    a.set_title('Turbo file-size change vs high-quality original')
    a.set_xlabel('Percent (negative means smaller)')
    a = axs[1, 1]
    changes = [r['psnr_delta_db'] for r in rows]
    a.barh(pos, changes, color=[green if v >= 0 else amber for v in changes])
    a.axvline(0, color='#f8fafc', alpha=.5)
    a.set_yticks(pos, labels); a.invert_yaxis()
    a.set_title('Turbo decoded PSNR difference vs original')
    a.set_xlabel('dB (negative means lower fidelity)')
    fig.suptitle('Custom MobiPEG V4 — 9 full-length video comparisons',
                 color='white', fontsize=19, fontweight='bold')
    fig.savefig(output / 'comparison_dashboard.png', dpi=165, facecolor=fig.get_facecolor())
    plt.close(fig)


def save_progress(args, rows):
    if not rows:
        return
    (args.output / 'summary.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False) + '\n')
    with (args.output / 'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    report = ['# Nine-video MobiPEG V4 quality-versus-turbo comparison', '',
              'All rows are full-length 2D conversions at 400×240, 30000/1001 FPS,',
              'QP12, subme9, GOP60, and eight-way GOP-parallel processing.',
              'The only codec experiment is `MOBI_INTRA_RD_CAP=3` and',
              '`MOBI_INTRA_RD_POLICY=1` in the turbo variant.',
              'Video and audio streams are checked; full output video is decoded.',
              'These are Linux Xeon host measurements, **not 3DS hardware playback tests**.',
              'FPS varies with machine load and source complexity.', '',
              '| Clip | Frames | Quality full FPS | Turbo full FPS | Quality encode FPS | Turbo encode FPS | Q PSNR | T PSNR | Size delta |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        report.append(f"| {r['slug']} | {r['frames']} | {r['quality_fps_total']:.1f} | {r['turbo_fps_total']:.1f} | {r['quality_fps_encode']:.1f} | {r['turbo_fps_encode']:.1f} | {r['quality_psnr_db']:.3f} | {r['turbo_psnr_db']:.3f} | {r['size_delta_percent']:+.1f}% |")
    report += ['', 'PSNR compares each fully decoded MOFLEX output against the same',
               'separately normalized 400×240 Y4M reference, and is an objective',
               'distortion measurement rather than a subjective quality guarantee.',
               'Turbo is **experimental**; its bitstream is not identical to quality mode.',
               'Both variants require additional physical 3DS playback testing.']
    (args.output / 'COMPARISON_REPORT.md').write_text('\n'.join(report) + '\n')
    produce_charts(rows, args.output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ffmpeg', type=Path, required=True)
    p.add_argument('--ffprobe', type=Path, required=True)
    p.add_argument('--parallel', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--only', nargs='*', default=None)
    p.add_argument('--resume', action='store_true')
    args = p.parse_args()
    for binary in (args.ffmpeg, args.ffprobe, args.parallel):
        if not binary.is_file(): p.error(f'Not found: {binary}')
    args.output.mkdir(parents=True, exist_ok=True)
    wanted = [x for x in CLIPS if args.only is None or x[0] in args.only]
    if not wanted: p.error('No matching clip slugs')
    prior = args.output / 'summary.json'
    rows_by_slug = {x['slug']: x for x in json.loads(prior.read_text())} if args.resume and prior.is_file() else {}
    for index, (slug, filename) in enumerate(wanted, 1):
        source = args.source_dir / filename
        if not source.is_file(): raise FileNotFoundError(source)
        print(f'\n[{index}/{len(wanted)}] {filename}', flush=True)
        if args.resume and slug in rows_by_slug:
            if all((args.output / mode / f'{slug}_{mode}.moflex').is_file() for mode in ('quality','turbo')):
                print(f'  reused completed pair {slug}', flush=True)
                continue
        source_audio = any(x['codec_type'] == 'audio' for x in probe_streams(args.ffprobe, source))
        results = {}
        for mode in ('quality', 'turbo'):
            target, results[mode] = run_conversion(args, slug, source, mode)
            result_audio = any(x['codec_type'] == 'audio' for x in probe_streams(args.ffprobe, target))
            if source_audio and not result_audio:
                raise RuntimeError(f'{slug} {mode} unexpectedly lost its audio')
            print(f"  {mode:7s}: {results[mode]['fps_total']:7.1f} FPS total, "
                  f"{results[mode]['fps_parallel_encode_only']:7.1f} FPS encode, "
                  f"{results[mode]['bytes']/1048576:7.2f} MiB", flush=True)
        with tempfile.TemporaryDirectory(prefix=f'mobipeg-quality-{slug}-') as td:
            norm = Path(td) / 'reference.y4m'
            norm_cfg = SimpleNamespace(eye_width=400, eye_height=240,
                                       fps='30000/1001', stereo_sbs=False)
            normalized_video(args.ffmpeg, source, norm, norm_cfg)
            q = quality_score(args.ffmpeg, norm, args.output / 'quality' / f'{slug}_quality.moflex')
            t = quality_score(args.ffmpeg, norm, args.output / 'turbo' / f'{slug}_turbo.moflex')
        a, b = results['quality'], results['turbo']
        if a['frames'] != b['frames'] or a['width'] != b['width'] or a['height'] != b['height']:
            raise RuntimeError(f'{slug} dimensions/frame counts differ between variants')
        row = dict(slug=slug, original_name=filename, frames=a['frames'],
                   duration_seconds=round(a['frames'] * 1001 / 30000, 3),
                   quality_fps_total=a['fps_total'], turbo_fps_total=b['fps_total'],
                   quality_fps_encode=a['fps_parallel_encode_only'],
                   turbo_fps_encode=b['fps_parallel_encode_only'],
                   full_speedup=round(b['fps_total']/a['fps_total'], 3),
                   encode_speedup=round(b['fps_parallel_encode_only']/a['fps_parallel_encode_only'], 3),
                   quality_psnr_db=q, turbo_psnr_db=t, psnr_delta_db=round(t-q, 5),
                   quality_bytes=a['bytes'], turbo_bytes=b['bytes'],
                   size_delta_percent=round(100 * (b['bytes']/a['bytes'] - 1), 3),
                   audio_preserved=source_audio,
                   quality_decoded_md5=a['decoded_video_md5'], turbo_decoded_md5=b['decoded_video_md5'])
        rows_by_slug[slug] = row
        save_progress(args, list(rows_by_slug.values()))
        print(f'  PSNR {q:.3f} vs {t:.3f} dB, size {row["size_delta_percent"]:+.2f}%', flush=True)
    print(f'\nFinished {len(rows_by_slug)} pairs; report: {args.output}/COMPARISON_REPORT.md', flush=True)


if __name__ == '__main__': main()
