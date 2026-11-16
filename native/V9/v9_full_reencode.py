#!/usr/bin/env python3
"""MobiPEG V9: decoder-verified R-D search over an existing V8 stereo profile.

Experimental Avatar-specific reproducer. Does not use Nintendo encoder binaries.
Inputs include the machine-readable V8 reference profile and its experiment
metadata; no absolute original workspace paths are needed.

The 45 V8-era GOPs must reproduce their original byte counts. Five legacy V7
GOPs may have changed code versions and are explicitly re-encoded as a
separate baseline, with mismatches recorded rather than silently ignored.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from v9_texture_sweep import FRAME_BYTES, metrics

EYE_FPS = 48
VARIANTS = {
    'baseline': {},
    'luma4': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '4', 'MOBI_CHROMA_DZ': '5'},
    'luma5': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'},
    'luma6': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '6', 'MOBI_CHROMA_DZ': '5'},
    'luma7': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '7', 'MOBI_CHROMA_DZ': '5'},
    'luma8': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_DZ': '8', 'MOBI_CHROMA_DZ': '5'},
    'flat12_5': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '12',
                 'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'},
    'flat24_5': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '24',
                 'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'},
    'flat48_5': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '48',
                 'MOBI_DZ': '5', 'MOBI_CHROMA_DZ': '5'},
    'flat24_4': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '24',
                 'MOBI_DZ': '4', 'MOBI_CHROMA_DZ': '5'},
    'flat24_6': {'MOBI_V9_INTER_LUMA_DZ': '1', 'MOBI_V9_INTER_FLAT_RANGE': '24',
                 'MOBI_DZ': '6', 'MOBI_CHROMA_DZ': '5'},
}


def run(cmd, **kwargs):
    p = subprocess.run([str(a) for a in cmd], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, **kwargs)
    if p.returncode:
        raise RuntimeError(f'Exit {p.returncode}: {p.stderr[-1100:].decode(errors="replace")}')
    return p.stdout


def original_parameters(row, psy_by_index, long_by_index):
    name = row['option']
    idx = row['index']
    extras = []
    if name in ('psyoff', 'umh', 'psyoff_umh', 'nr10'):
        info = psy_by_index.get((idx, name))
        if info is None:
            raise ValueError(f'V8 metadata missing for {idx} {name}')
        if name in ('psyoff', 'psyoff_umh'):
            extras += ['-psy', '0']
        if name in ('umh', 'psyoff_umh'):
            extras += ['-me_method', 'umh']
        if name == 'nr10':
            extras += ['-noise_reduction', '10']
        return info['qyx'], info['qp'], info.get('lambda_delta', 0), extras
    if row['span'] == 2:
        info = long_by_index.get((idx, name))
        if info is None:
            raise ValueError(f'V8 four-second metadata missing for {idx} {name}')
        return info['qyx'], info['qp'], info.get('lambda_delta', 0), extras
    # V7 trial names encode the qyx, qp and lambda offset.
    quant = {'detail46': (3, 16), 'detail47': (3, 17),
             'reference48': (4, 12), 'save49': (4, 13), 'save50': (4, 14)}
    tag, _, suffix = name.partition('_lambda')
    if tag not in quant:
        raise ValueError(f'Unrecognized V8 variant {idx} {name}')
    return (*quant[tag], int(suffix) if suffix else 0, extras)


def measure(args):
    row, variant, raw_path, outfile, enc, probe, params = args
    qyx, qp, lam, extra = params
    n = row['coded_frames']
    cmd = [enc, '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
           '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-video_size', '400x224',
           '-framerate', str(EYE_FPS), '-i', raw_path, '-an',
           '-c:v', 'mobiclip', '-mobiclip', '1', '-qp', str(qp),
           '-mobi_qyx', str(qyx), '-preset', 'medium',
           '-me_method', 'hex', '-g', str(n)] + extra + [
           '-mo_layout', '0', '-f', 'moflex', outfile]
    env = {**os.environ, 'MOBI_SUBME': '9', 'MOBI_SKIP': '0',
           'MOBI_QYX_RDO': '0', 'MOBI_INTRA_RD_CAP': '0',
           'MOBI_RDO_PRED_COST': '0', 'MOBI_RDO_LAMBDA_DELTA': str(lam),
           **VARIANTS[variant]}
    # Expunge custom changes inherited from the user's environment for baseline.
    for key in ('MOBI_DZ', 'MOBI_CHROMA_DZ',
                'MOBI_V9_INTER_LUMA_DZ', 'MOBI_V9_INTER_FLAT_RANGE',
                'MOBI_V9_FLAT_DZ', 'MOBI_V9_FLAT_RANGE', 'MOBI_V9_FLAT_INTRA'):
        if key not in VARIANTS[variant]:
            env.pop(key, None)
    began = time.monotonic()
    run(cmd, env=env, timeout=300)
    rec = run([enc, '-nostdin', '-hide_banner', '-loglevel', 'error',
               '-xerror', '-i', outfile, '-map', '0:v:0',
               '-pix_fmt', 'yuv420p', '-f', 'rawvideo', 'pipe:1'], timeout=120)
    if len(rec) != n * FRAME_BYTES:
        raise ValueError(f'Expected {n} coded eye frames; got {len(rec) // FRAME_BYTES}')
    packet_sizes = run([probe, '-v', 'error', '-select_streams', 'v:0',
                        '-show_entries', 'packet=size', '-of', 'csv=p=0', outfile])
    pkt = [int(z) for z in packet_sizes.split()]
    if len(pkt) != n:
        raise ValueError(f'Packet count mismatch {len(pkt)} vs {n}')
    score = metrics(Path(raw_path).read_bytes(), rec, n=n)
    second_bytes=[sum(pkt[i:i+48]) for i in range(0,len(pkt),48) if len(pkt[i:i+48])==48]
    return {'index': row['index'], 'span': row['span'],
            'coded_frames': n, 'v8_option': row['option'], 'variant': variant,
            'qyx': qyx, 'qp': qp, 'lambda_delta': lam,
            'file': str(outfile), 'video_bytes': sum(pkt),
            'peak_1s_bytes':max(second_bytes) if second_bytes else 0,
            'measured_seconds': round(time.monotonic()-began, 3), **score}


def select(rows, budget, profile='conservative', peak_ceiling_bytes=None):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r['index']].append(r)
    keys = sorted(groups)
    if not keys:
        raise ValueError('No complete GOP experiments supplied')
    base = [next(z for z in groups[k] if z['variant'] == 'baseline') for k in keys]
    base_bytes = sum(z['video_bytes'] for z in base)
    margin = budget - base_bytes
    if margin < 0:
        raise ValueError(f'Baseline {base_bytes} bytes already exceeds budget {budget}')
    texture = profile == 'texture'

    def quality_score(new, old):
        # Reward genuine source fidelity, structural retention, and less grain.
        return ((old['mse']-new['mse']) / max(old['mse'], .01))*(4.0 if texture else 8.0) + \
               (new['ssim']-old['ssim'])*(160.0 if texture else 45.0) + \
               (old['grain']-new['grain'])*(1.5 if texture else .6) + \
               ((old['edge_mse']-new['edge_mse'])/max(old['edge_mse'], .01))*.6 + \
               ((old['flicker_mse']-new['flicker_mse'])/max(old['flicker_mse'], .01))*.2

    options = []
    for k, b in zip(keys, base):
        allowed = []
        for z in groups[k]:
            delta_score = quality_score(z,b) if z['variant'] != 'baseline' else 0.0
            # Guards apply at GOP level, before global bitrate knapsack.
            mse_limit = b['mse'] + (max(1.3, b['mse']*.065) if texture else .1)
            edge_limit = b['edge_mse'] + (max(2.0,b['edge_mse']*.025) if texture else .65)
            cut_limit = b['cut_mse'] + (max(3.0,b['cut_mse']*.065) if texture else .5)
            if z['variant'] != 'baseline' and (
                (peak_ceiling_bytes is not None and z['peak_1s_bytes'] > peak_ceiling_bytes) or
                z['mse'] > mse_limit or
                z['ssim'] < b['ssim'] - (.00013 if texture else .00018) or
                z['edge_mse'] > edge_limit or
                z['grain'] > b['grain'] + (.005 if texture else .012) or
                z['cut_mse'] > cut_limit or
                not math.isfinite(delta_score) or delta_score <= 0):
                continue
            allowed.append((z, delta_score))
        options.append(allowed)

    # DP over deltas to the exactly reproduced V8 baseline. Size in ~512-B
    # buckets; round positive increases upward for a conservative final size.
    # Negative deltas are retained accurately using bucket-size rounding.
    gran = 512
    states = {0: (0., [])}
    for g, (cands, b) in enumerate(zip(options, base)):
        future = {}
        for cost, (score, choices) in states.items():
            for z, benefit in cands:
                delta = z['video_bytes']-b['video_bytes']
                rounded = math.ceil(delta/gran) if delta >= 0 else math.ceil(delta/gran)
                new_cost = cost + rounded
                if new_cost > math.floor(margin / gran) + (600 if texture else 0):
                    continue
                new_score = score + benefit
                if new_cost not in future or new_score > future[new_cost][0]:
                    future[new_cost] = (new_score, choices+[z])
        # Keep only best score as cost rises. A more expensive state with no
        # larger score can never beat the cheaper state in future GOPs.
        states = {}
        best = -1e20
        for size, item in sorted(future.items()):
            if item[0] > best + 1e-8:
                best = item[0]
                states[size] = item
        print(f'Selecting GOP {g+1:02d}/{len(base)}, states={len(states)}', flush=True)
    if not states:
        raise RuntimeError('No size-feasible quality profile')
    feasible = [(size,score,choice) for size,(score,choice) in states.items()
                if size*gran <= margin]
    if not feasible:
        raise RuntimeError('No final size-feasible profile')
    winner = max(feasible,key=lambda x:x[1])[2]
    actual = sum(z['video_bytes'] for z in winner)
    if actual > budget:
        raise RuntimeError(f'Knapsack rounding failed: {actual} > {budget}')
    return winner, base, margin


def mux(selection, encoder, source_mp4, raw, outdir, final, probe):
    gops = sorted(selection, key=lambda z:z['index'])
    filelist = outdir / 'V9_VIDEO_COMBINE.ffconcat'
    # Video-only input has 48 coded frames per second.
    filelist.write_text('ffconcat version 1.0\n' + ''.join(
        f"file '{Path(z['file']).resolve()}'\nduration {z['coded_frames']/EYE_FPS:.9f}\n"
        for z in gops))
    pcm = outdir / 'audio_pcm_44100_s16le.pcm'
    if not pcm.exists():
        run(['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
             '-i', source_mp4, '-map', '0:a:0', '-ar', '44100', '-ac', '2',
             '-c:a', 'pcm_s16le', '-f', 's16le', pcm], timeout=300)
    run([encoder, '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
         '-f', 'concat', '-safe', '0', '-i', filelist,
         '-f', 's16le', '-ar', '44100', '-ac', '2', '-i', pcm,
         '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
         '-c:a', 'pcm_s16le', '-mo_audio', 'adpcm', '-mo_layout', '0',
         '-mo_interleave_input_double_rate', '1', '-f', 'moflex', final], timeout=400)
    packet_sizes = run([probe, '-v', 'error', '-select_streams', 'v:0',
                        '-show_entries', 'packet=size', '-of', 'csv=p=0', final])
    pkt = [int(z) for z in packet_sizes.split()]
    if len(pkt) != sum(z['coded_frames'] for z in selection):
        raise RuntimeError('Full mux packet count mismatch')
    if sum(pkt) != sum(z['video_bytes'] for z in selection):
        raise RuntimeError('Full mux video payload mismatch')
    for stream in ('v:0','a:0'):
        run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
             '-xerror', '-i', final, '-map', f'0:{stream}',
             '-f', 'null', '-'], timeout=500)
    return {'packet_count':len(pkt), 'video_bytes':sum(pkt),
            'file_bytes':Path(final).stat().st_size,
            'sha256':hashlib.sha256(Path(final).read_bytes()).hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw', type=Path, required=True)
    ap.add_argument('--mp4', type=Path, required=True)
    ap.add_argument('--encoder', type=Path, required=True)
    ap.add_argument('--probe', type=Path, required=True)
    ap.add_argument('--selection', type=Path, required=True)
    ap.add_argument('--psy-metadata', type=Path, required=True)
    ap.add_argument('--long-metadata', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--budget', type=int, default=None,
                    help='Target video packet bytes; default 1266.5 kbps across input duration')
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--variants', nargs='+', choices=list(VARIANTS), default=list(VARIANTS))
    ap.add_argument('--test-only', action='store_true')
    ap.add_argument('--profile',choices=['conservative','texture'],default='conservative')
    ap.add_argument('--optimize-only',action='store_true')
    ap.add_argument('--output-name',default=None,
                    help='Output MOFLEX basename (default: Avatar research candidate)')
    ap.add_argument('--report-name',default=None,
                    help='Custom output JSON report basename')
    ap.add_argument('--peak-1s-kbps',type=float,default=None,
                    help='Reject new GOP variants with any 1-second payload spike above this kbps')
    a = ap.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sel = json.loads(a.selection.read_text())
    # The portable V8 runner uses plain 2-second rows without a span field.
    for r in sel: r.setdefault('span',1)
    psy = {(x['index'], x['option']):x for x in json.loads(a.psy_metadata.read_text())}
    lng = {(x['index'], x['option']):x for x in json.loads(a.long_metadata.read_text())}
    if sum(x['coded_frames'] for x in sel) * FRAME_BYTES != a.raw.stat().st_size:
        raise ValueError('V8 selection does not match source frame count')
    if a.budget is None:
        a.budget = int(1266.5*1000/8 * (sum(x['coded_frames'] for x in sel)/EYE_FPS))
    rawpart = {}
    params = {}
    with a.raw.open('rb') as f:
        for r in sel:
            idx = r['index']
            f.seek(idx * 96 * FRAME_BYTES)
            data = f.read(r['coded_frames']*FRAME_BYTES)
            dest = out / f'gop_{idx:03d}_source.yuv'
            if (not dest.exists() or dest.stat().st_size != len(data) or
                hashlib.sha256(dest.read_bytes()).digest() != hashlib.sha256(data).digest()):
                dest.write_bytes(data)
            rawpart[idx] = dest
            params[idx] = original_parameters(r, psy, lng)
    # Decoder-verified experiments are only reusable for the exact source,
    # codec executable and profiles. Prevent cross-movie cache corruption.
    cache_path = out / 'v9_verified_gop_results.json'
    signature_path = out / 'v9_cache_signature.json'
    signature = {
        'raw_sha256': hashlib.sha256(a.raw.read_bytes()).hexdigest(),
        'encoder_sha256': hashlib.sha256(a.encoder.read_bytes()).hexdigest(),
        'selection_sha256': hashlib.sha256(a.selection.read_bytes()).hexdigest(),
        'psy_sha256': hashlib.sha256(a.psy_metadata.read_bytes()).hexdigest(),
        'long_sha256': hashlib.sha256(a.long_metadata.read_bytes()).hexdigest(),
        'variants': VARIANTS,
    }
    if signature_path.exists() and json.loads(signature_path.read_text()) == signature:
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else []
    else:
        if cache_path.exists():
            print('Invalidating V9 cache: source, encoder or profile changed', flush=True)
        cache = []
        signature_path.write_text(json.dumps(signature, indent=2))
    completed = {(r['index'], r['variant']):r for r in cache}
    jobs = [(r, variant, rawpart[r['index']],
             out / f"gop_{r['index']:03d}_{variant}.moflex",
             a.encoder, a.probe, params[r['index']])
            for r in sel for variant in a.variants
            if (r['index'],variant) not in completed]
    if a.optimize_only:jobs=[]
    print(f'V9 searching {len(jobs)} configurations, cached {len(cache)}', flush=True)
    bad = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(measure, j): j for j in jobs}
        for k, future in enumerate(concurrent.futures.as_completed(futures), 1):
            j = futures[future]
            try:
                r = future.result()
                if r['variant'] == 'baseline' and r['video_bytes'] != j[0]['video_bytes']:
                    # V8 included five old V7 GOP files from an earlier
                    # encoder build; their exact original streams are not
                    # in the current artifact bundle. Limit exceptions to
                    # that known legacy category and explicitly annotate.
                    relative = abs(r['video_bytes'] - j[0]['video_bytes']) / j[0]['video_bytes']
                    if not (j[0]['option'] == 'detail47_lambda2' and relative < .01):
                        raise RuntimeError(f'Unexpected V8 baseline mismatch at GOP {r["index"]}: '
                                           f'{r["video_bytes"]} vs {j[0]["video_bytes"]}')
                    r['legacy_v7_reencoded'] = True
                    r['original_v8_payload_bytes'] = j[0]['video_bytes']
                    print('LEGACY V7 NOTE:',r['index'],'original=',j[0]['video_bytes'],
                          'local=',r['video_bytes'],flush=True)
                completed[(r['index'], r['variant'])] = r
                cache_path.write_text(json.dumps(sorted(completed.values(),
                    key=lambda z:(z['index'],z['variant'])),indent=2))
                print(f'{k:03d}/{len(jobs)} GOP={r["index"]:02d} {r["variant"]:<8} '
                      f'{r["video_bytes"]}B PSNR={r["psnr"]:.3f} '
                      f'SSIM={r["ssim"]:.4f} grain={r["grain"]:.3f}', flush=True)
            except Exception as e:
                bad.append({'gop':j[0]['index'],'variant':j[1],'error':str(e)})
                print('REJECT',bad[-1],flush=True)
    (out / 'v9_trial_failures.json').write_text(json.dumps(bad,indent=2))
    if a.test_only: return
    wanted = [(r['index'],variant) for r in sel for variant in a.variants]
    missing = [w for w in wanted if w not in completed]
    if missing: raise RuntimeError(f'Incomplete tested profile: {missing[:20]}')
    if a.peak_1s_kbps is not None:
        # Historical cached trials predate the per-second bitrate statistic.
        # Reconstruct it from each actual verified candidate packet stream.
        needs=[z for z in completed.values() if 'peak_1s_bytes' not in z]
        print('Measuring packet peaks for',len(needs),'cached candidate GOPs',flush=True)
        def packet_peak(z):
            data=run([a.probe,'-v','error','-select_streams','v:0',
                '-show_entries','packet=size','-of','csv=p=0',z['file']])
            sizes=[int(s) for s in data.split()]
            if len(sizes)!=z['coded_frames']:raise ValueError('Peak audit packet mismatch')
            return max([sum(sizes[i:i+48]) for i in range(0,len(sizes),48)
                        if len(sizes[i:i+48])==48] or [0])
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(8,a.workers))) as pool:
            futures={pool.submit(packet_peak,z):z for z in needs}
            for i,future in enumerate(concurrent.futures.as_completed(futures),1):
                futures[future]['peak_1s_bytes']=future.result()
                if i%50==0:print('Peak-audited',i,'/',len(needs),flush=True)
        cache_path.write_text(json.dumps(sorted(completed.values(),
            key=lambda z:(z['index'],z['variant'])),indent=2))
    # Repair legacy NaNs from no-edge GOP metrics; newer evals use MSE there.
    for row in completed.values():
        for fld in ('edge_mse','flicker_mse'):
            if not math.isfinite(row[fld]): row[fld]=row['mse'] if fld=='edge_mse' else 0.0
    peak_ceiling=(math.floor(a.peak_1s_kbps*1000/8) if a.peak_1s_kbps is not None else None)
    winning, baseline, margin = select(list(completed.values()), a.budget,
                                      profile=a.profile,peak_ceiling_bytes=peak_ceiling)
    print('V9 selected',collections.Counter(r['variant'] for r in winning),flush=True)
    suffix='TextureFocus' if a.profile=='texture' else 'PredictiveLuma'
    final = out / (a.output_name or f'Avatar_3D_MobiPEG_V9_{suffix}.moflex')
    check = mux(winning, a.encoder, a.mp4, a.raw, out, final, a.probe)
    report = {'experimental':True, 'profile':a.profile, 'format':'MOFLEX stereo layout 0',
      'new_variant_peak_kbps_ceiling':a.peak_1s_kbps,
      'coded_eye_frames':sum(z['coded_frames'] for z in winning),
      'reference_video_bytes':a.budget, 'v8_video_bytes':sum(z['video_bytes'] for z in baseline),
      'v9_video_bytes':check['video_bytes'], 'v8_release_margin':margin,
      'tested_gop_variants':len(completed), 'rejected_variants':bad,
      'reencoded_legacy_v7_gops':[
          {'gop':z['index'],'v8_bytes':z['original_v8_payload_bytes'],
           'rebuilt_bytes':z['video_bytes']}
          for z in baseline if z.get('legacy_v7_reencoded')],
      'selected_modes':dict(collections.Counter(z['variant'] for z in winning)),
      'selected_gops':winning, 'v8_reference_gops':baseline,
      'final_file':str(final), 'verified_output':check,
      'hardware_verification':'PENDING: Old 3DS Nintendo 3D Movie Viewer'}
    report_name='V9_TEXTURE_QUALITY_REPORT.json' if a.profile=='texture' else 'V9_QUALITY_REPORT.json'
    if a.report_name: report_name=a.report_name
    (out / report_name).write_text(json.dumps(report,indent=2))
    print('COMPLETE',json.dumps({k:report[k] for k in ('v8_video_bytes','v9_video_bytes',
          'tested_gop_variants','selected_modes','verified_output')},indent=2),flush=True)


if __name__ == '__main__': main()
