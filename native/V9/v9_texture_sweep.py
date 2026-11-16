#!/usr/bin/env python3
"""Compare decoder-verified MobiClip encoder quantization modes on matched samples.

Independent source-reference comparison. These are not Old 3DS hardware results.
"""
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from scipy.ndimage import gaussian_filter, uniform_filter

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'work'
ENC = WORK / 'MobiPEG_Custom_V8/local/bin/ffmpeg'
PROBE = WORK / 'MobiPEG_Custom_V8/local/bin/ffprobe'
SOURCE = WORK / 'Avatar_eyes_400x224_48fps.yuv'
OUT = WORK / 'v9_sweep'
W, H = 400, 224
PIXELS = W * H
FRAME_BYTES = PIXELS * 3 // 2
N = 96
SCENES = [12, 54, 82, 94]

MODES = {
    'baseline': ({}, []),
    'dz1': ({'MOBI_DZ': '1'}, []),
    'dz2': ({'MOBI_DZ': '2'}, []),
    'dz3': ({'MOBI_DZ': '3'}, []),
    'dz4': ({'MOBI_DZ': '4'}, []),
    'dz6': ({'MOBI_DZ': '6'}, []),
    'dz7': ({'MOBI_DZ': '7'}, []),
    'dz8': ({'MOBI_DZ': '8'}, []),
    'act30flat': ({'MOBI_ACT30_LUMADC_ENABLE': '1'}, []),
    'act30var12': ({'MOBI_ACT30_LUMADC_ENABLE': '1', 'MOBI_ACT30_LUMADC_VAR': '12'}, []),
    'act26chroma': ({'MOBI_ACT26_CDZ_ENABLE': '1', 'MOBI_ACT26_CDZ_VAR': '8'}, []),
    'act36lumaoff': ({'MOBI_ACT36_NORM_LUMA': '0'}, []),
    'act36chromaoff': ({'MOBI_ACT36_NORM_CHROMA': '0'}, []),
    'dz3flat': ({'MOBI_DZ': '3', 'MOBI_ACT30_LUMADC_ENABLE': '1'}, []),
    'dz3chroma': ({'MOBI_DZ': '3', 'MOBI_ACT26_CDZ_ENABLE': '1', 'MOBI_ACT26_CDZ_VAR': '8'}, []),
    'psy_on': ({}, ['-psy', '1']),
    'psy_off_umh': ({}, ['-me_method', 'umh']),
    'act22_rdo': ({'MOBI_ACT22_RDO_ENABLE': '1'}, []),
    'act23_trellis': ({'MOBI_ACT23_TRELLIS_ENABLE': '1'}, []),
    'act24_plsplit': ({'MOBI_ACT24_PLSPLIT_ENABLE': '1'}, []),
    'act24_intraoff': ({'MOBI_ACT24_INTRAFULL_ENABLE': '0'}, []),
    'dz1_act22': ({'MOBI_DZ': '1', 'MOBI_ACT22_RDO_ENABLE': '1'}, []),
    'flat0r4': ({'MOBI_V9_FLAT_DZ': '0', 'MOBI_V9_FLAT_RANGE': '4'}, []),
    'flat1r8': ({'MOBI_V9_FLAT_DZ': '1', 'MOBI_V9_FLAT_RANGE': '8'}, []),
    'flat0r12': ({'MOBI_V9_FLAT_DZ': '0', 'MOBI_V9_FLAT_RANGE': '12'}, []),
    'flat1r12': ({'MOBI_V9_FLAT_DZ': '1', 'MOBI_V9_FLAT_RANGE': '12'}, []),
    'flat2r12': ({'MOBI_V9_FLAT_DZ': '2', 'MOBI_V9_FLAT_RANGE': '12'}, []),
    'flat1r20': ({'MOBI_V9_FLAT_DZ': '1', 'MOBI_V9_FLAT_RANGE': '20'}, []),
    'flat0r20': ({'MOBI_V9_FLAT_DZ': '0', 'MOBI_V9_FLAT_RANGE': '20'}, []),
    'flat1r32': ({'MOBI_V9_FLAT_DZ': '1', 'MOBI_V9_FLAT_RANGE': '32'}, []),
    'flat1r12inter': ({'MOBI_V9_FLAT_DZ': '1', 'MOBI_V9_FLAT_RANGE': '12',
                      'MOBI_V9_FLAT_INTRA': '0'}, []),
    'flat0r20inter': ({'MOBI_V9_FLAT_DZ': '0', 'MOBI_V9_FLAT_RANGE': '20',
                      'MOBI_V9_FLAT_INTRA': '0'}, []),
    'interdz1': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '1'}, []),
    'interdz2': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '2'}, []),
    'interdz3': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '3'}, []),
    'interdz4': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '4'}, []),
    'interdz5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '5'}, []),
    'interdz6': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '6'}, []),
    'interdz7': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '7'}, []),
    'interdz8': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '8'}, []),
    'interdz4flat': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '4',
                     'MOBI_V9_FLAT_DZ': '1', 'MOBI_V9_FLAT_RANGE': '12'}, []),
    'luma5_chroma5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '5',
                      'MOBI_CHROMA_DZ': '5'}, []),
    'luma6_chroma5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '6',
                      'MOBI_CHROMA_DZ': '5'}, []),
    'luma7_chroma5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '7',
                      'MOBI_CHROMA_DZ': '5'}, []),
    'luma8_chroma5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '8',
                      'MOBI_CHROMA_DZ': '5'}, []),
    'interflat8dz5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '8',
                      'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat12dz5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '12',
                       'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat20dz5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '20',
                       'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat24dz5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '24',
                       'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat32dz5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '32',
                       'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat48dz5': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '48',
                       'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat12dz4': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '12',
                       'MOBI_DZ': '4', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat24dz4': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '24',
                       'MOBI_DZ': '4', 'MOBI_CHROMA_DZ': '5'}, []),
    'interflat24dz6': ({'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '24',
                       'MOBI_DZ': '6', 'MOBI_CHROMA_DZ': '5'}, []),
}


def run(args, **kwargs):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if p.returncode:
        raise RuntimeError(f'{args[0]} rc={p.returncode}: {p.stderr[-1500:].decode(errors="replace")}')
    return p.stdout


def local_ssim(x, y):
    # Original SSIM structure, 7x7 rectangular local window; same method for all cases.
    x = x.astype(np.float32)
    y = y.astype(np.float32)
    mx = uniform_filter(x, 7)
    my = uniform_filter(y, 7)
    vx = uniform_filter(x * x, 7) - mx * mx
    vy = uniform_filter(y * y, 7) - my * my
    cov = uniform_filter(x * y, 7) - mx * my
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    return float(np.mean(((2 * mx * my + c1) * (2 * cov + c2)) /
                         ((mx * mx + my * my + c1) * (vx + vy + c2))))


def metrics(src, decoded, n=N):
    s = np.frombuffer(src, dtype=np.uint8).reshape(n, FRAME_BYTES)
    d = np.frombuffer(decoded, dtype=np.uint8).reshape(n, FRAME_BYTES)
    lum = s[:, :PIXELS].reshape(n, H, W)
    dst = d[:, :PIXELS].reshape(n, H, W)
    delta = lum.astype(np.int16) - dst.astype(np.int16)
    sse = np.square(delta.astype(np.float32))
    mse = float(sse.mean())
    er = np.abs(np.diff(lum.astype(np.int16), axis=1, prepend=lum[:, :1])) > 24
    ec = np.abs(np.diff(lum.astype(np.int16), axis=2, prepend=lum[:, :, :1])) > 24
    edges = er | ec
    cut = np.mean(sse[:min(n, 12)])
    # Two eyes, uniformly sampled within the GOP.
    samples = list(range(0, n, 12)) + list(range(1, n, 12))
    ss = float(np.mean([local_ssim(lum[i], dst[i]) for i in samples]))
    # Grain proxy: reconstructed high-frequency energy in source-flat pixels.
    grain_src, grain_dec, flicker = [], [], []
    for i in samples:
        orig = lum[i].astype(np.float32)
        rec = dst[i].astype(np.float32)
        edges_y = np.abs(np.diff(orig, axis=0, prepend=orig[:1]))
        edges_x = np.abs(np.diff(orig, axis=1, prepend=orig[:, :1]))
        mask = (edges_x + edges_y) < 12
        if mask.sum() > 300:
            grain_src.append(float(np.abs(orig - gaussian_filter(orig, 0.6))[mask].mean()))
            grain_dec.append(float(np.abs(rec - gaussian_filter(rec, 0.6))[mask].mean()))
    for i in samples:
        if i < 2: continue
        refd = lum[i].astype(np.int16) - lum[i-2].astype(np.int16)
        decd = dst[i].astype(np.int16) - dst[i-2].astype(np.int16)
        static = np.abs(refd) <= 3
        if static.sum() > 300:
            e = (refd[static] - decd[static]).astype(np.float32)
            flicker.append(float(np.mean(e * e)))
    return {'psnr': 10 * math.log10(65025 / mse), 'ssim': ss,
            'mse': mse, 'edge_mse': float(sse[edges].mean()) if np.any(edges) else mse,
            'cut_mse': float(cut), 'grain': float(np.mean(grain_dec)),
            'source_grain': float(np.mean(grain_src)),
            'grain_excess': float(np.mean(grain_dec) - np.mean(grain_src)),
            'flicker_mse': float(np.mean(flicker)) if flicker else 0.0}


def test(args):
    scene, mode, qyx = args
    envvars, switches = MODES[mode]
    raw = OUT / f'source_{scene}.raw'
    encoded = OUT / f'{scene}_{mode}_q{qyx}.moflex'
    cmd = [str(ENC), '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
           '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-video_size', '400x224',
           '-framerate', '48', '-i', str(raw), '-an', '-c:v', 'mobiclip',
           '-mobiclip', '1', '-qp', '12', '-mobi_qyx', str(qyx),
           '-preset', 'medium', '-me_method', 'hex', '-g', '96',
           '-threads', '1', '-psy', '0'] + switches + [
           '-mo_layout', '0', '-f', 'moflex', str(encoded)]
    env = {**os.environ, 'MOBI_SUBME': '9', 'MOBI_SKIP': '0',
           'MOBI_QYX_RDO': '0', 'MOBI_INTRA_RD_CAP': '0',
           'MOBI_RDO_LAMBDA_DELTA': '0', **envvars}
    started = time.monotonic()
    run(cmd, env=env, timeout=240)
    dec = run([str(ENC), '-hide_banner', '-nostdin', '-loglevel', 'error',
               '-xerror', '-i', str(encoded), '-map', '0:v:0',
               '-pix_fmt', 'yuv420p', '-f', 'rawvideo', 'pipe:1'], timeout=120)
    if len(dec) != N * FRAME_BYTES:
        raise ValueError(f'Wrong frame count: {len(dec)} instead of {N * FRAME_BYTES}')
    info = run([str(PROBE), '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'packet=size', '-of', 'csv=p=0', str(encoded)])
    sizes = [int(z) for z in info.split()]
    if len(sizes) != N:
        raise ValueError(f'Wrong packet count: {len(sizes)} instead of {N}')
    src = raw.read_bytes()
    out = {'scene': scene, 'mode': mode, 'qyx': qyx, 'payload_bytes': sum(sizes),
           'encoded_bytes': encoded.stat().st_size, 'coded_frames': N,
           'elapsed': round(time.monotonic() - started, 3), **metrics(src, dec)}
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--qyx', type=int, nargs='+', default=[3, 4])
    parser.add_argument('--scenes', type=int, nargs='+', default=SCENES)
    parser.add_argument('--modes', nargs='+', default=list(MODES))
    parser.add_argument('--workers', type=int, default=4)
    p = parser.parse_args()
    OUT.mkdir(exist_ok=True, parents=True)
    if not ENC.exists():
        sys.exit('Custom encoder not yet compiled.')
    with SOURCE.open('rb') as f:
        for scene in p.scenes:
            expected = (scene * 48) * FRAME_BYTES
            f.seek(expected)
            part = f.read(N * FRAME_BYTES)
            if len(part) != N * FRAME_BYTES:
                raise ValueError('Source too short')
            dest = OUT / f'source_{scene}.raw'
            if not dest.exists() or dest.stat().st_size != len(part) or hashlib.sha256(dest.read_bytes()).digest() != hashlib.sha256(part).digest():
                dest.write_bytes(part)
    results_path = OUT / 'quant_sweep_results.json'
    existing = json.loads(results_path.read_text()) if results_path.exists() else []
    completed = {(z['scene'], z['mode'], z['qyx']) for z in existing}
    jobs = [(s, m, q) for s in p.scenes for m in p.modes for q in p.qyx if (s, m, q) not in completed]
    print('Starting sweep, jobs', len(jobs), 'already', len(completed), flush=True)
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=p.workers) as pool:
        futures = {pool.submit(test, j): j for j in jobs}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            job = futures[future]
            try:
                got = future.result()
                existing.append(got)
                results_path.write_text(json.dumps(sorted(existing, key=lambda z:(z['scene'], z['qyx'], z['mode'])), indent=2))
                print(f'{index}/{len(jobs)} scene={got["scene"]} mode={got["mode"]} '
                      f'q={got["qyx"]} bytes={got["payload_bytes"]} PSNR={got["psnr"]:.3f} '
                      f'SSIM={got["ssim"]:.4f} grain={got["grain"]:.3f}', flush=True)
            except Exception as e:
                failures.append({'job': job, 'error': str(e)})
                print('FAIL', job, e, flush=True)
    (OUT/'quant_sweep_failures.json').write_text(json.dumps(failures, indent=2))
    print('Done', len(existing), 'measured, failures', len(failures), flush=True)


if __name__ == '__main__':
    main()
