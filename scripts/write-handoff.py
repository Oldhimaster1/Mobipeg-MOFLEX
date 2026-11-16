import json
from pathlib import Path
root=Path(__file__).resolve().parent.parent
rows=json.loads((root/'reports/quality-analysis.json').read_text());r=next(x for x in rows if x['name']=='avatar-full-3d');a=r['analysis'];assert r['qualityParityPass'] and r['audioParityPass']
text=f'''# MobiPEG Web V15 — tested handoff

Read this first. The final half-SBS geometry rerun is now COMPLETE. Nothing has been published or deployed; the user will arrange hosting with their other AI.

## Run and rebuild

- `node scripts/dev-server.mjs`, then open http://localhost:4173.
- `dist/` is the website, including the real scalar and SIMD WASM engines.
- `native/source/ffmpeg` and `native/source/x264` contain full corresponding custom codec source.
- Rebuild using Emscripten 4.0.10: `bash scripts/build-wasm.sh`, then `bash scripts/build-simd.sh`, then `node scripts/provenance.mjs`.
- The local server only serves assets; videos are processed inside the browser and are not uploaded.

## Final corrected stereo result

The inherited half-SBS fitting bug is fixed in BOTH the Python wrapper and JS controller. They add `reset_sar=1` inside FFmpeg's scale filter only when the eye SAR is 2. This makes fitting use the eye's display aspect ratio instead of squeezed pixel dimensions. 2D/full-SBS paths are unchanged. The compiled native filter already supports this setting, so a codec rebuild was not required.

Final complete Avatar comparison, 400×224 per eye / 24 stereo pairs per second:

| Measure | Corrected native | Corrected WASM (SIMD) |
|---|---:|---:|
| Finished bytes | {r['native']['bytes']:,} | {r['wasm']['bytes']:,} |
| Coded eye frames | {r['native']['frames']:,} | {r['wasm']['frames']:,} |
| All-plane PSNR | {a['native']['psnr']} | {a['wasm']['psnr']} |
| SSIM All | {a['native']['ssim']} | {a['wasm']['ssim']} |

Full video/audio decode passed. Decoded audio PCM matches native exactly. The final native file was reused from its completed corrected encode, then independently reverified; its encode time was not retained. Final WASM conversion/verification took {r['wasm']['elapsedSeconds']:.2f}s on the development host, not a browser/device performance guarantee.

The files are not universally byte-identical across architectures; current quality differences are measured in the reports. Correcting the squeezed/pillarboxed image naturally increases file size compared with the old incorrect geometry. This port preserves the actual native codec/settings, rather than claiming new Nintendo-quality compression improvements.

## Completed checks

- 249 controller tests, including 180 direct Python/JS filter-graph comparisons and the SAR regression check.
- Original native suite: 11 passed, 4 skipped for absent exact named fixtures; real synthetic stereo/audio integration and eye-corner geometry checks passed.
- Full Anime, full Avatar and full Yip native/WASM comparisons; complete video/audio verification; all supported settings represented in the real matrix.
- Proper half-SBS red/blue fixture with squeezed 200×224 pixels per eye: native/WASM SIMD equality, plus actual Chrome download equality and near-corner pixel checks. This verifies full-frame geometry, not just eye-center colors.
- Stereo maximum-file-size trial encoding completed successfully with a 180,000-byte cap; impossible budgets and invalid media were rejected by the real engine.
- 10-minute low-complexity output retained all 14,400 frames and matched native byte-for-byte.
- Padded 128 MiB input accepted; this is a large-file handling test, not a feature-length movie stress test.
- Exact seek-versus-linear frame hashes and scene-cut checks were rerun for the final corrected outputs.
- Refreshed aligned source/native/WASM image comparisons are included.

See `reports/VALIDATION.md` and machine-readable reports. Earlier pre-SAR measurements are kept under `reports/history/`; they must not be substituted for the corrected results.

## Important implementation details

Preserve the Emscripten preRun initialization of MOBI settings. Setting ENV after module readiness was too late for C getenv in initial tests. Each CLI command needs a fresh WASM instance to clear cached process globals. Both encode and audio remux must retain stereo layout 0 and `mo_interleave_input_double_rate=1`; coded FPS is double display FPS and audio duration uses actual coded frames / coded FPS.

## Honest remaining limits

Physical iPhone Safari, Firefox/WebKit and actual Old3DS/New3DS playback were not available here and remain unverified. The optional external Playwright suite was not executed. GitHub Pages deployment was not tested and is left to the user's other AI. No deployment configuration has been added for it. Threading needs cross-origin isolation; the included local server sends the required headers directly. The service-worker fallback is included but not claimed as verified on GitHub Pages.

The normal native muxer still buffers media/packets to build its front seek table. WORKERFS avoids copying the original browser input but does not remove codec/muxer/output memory. Arbitrary feature-length/high-bitrate movies and total mobile tab-memory limits are not certified. No pause/resume or crash recovery is implemented.

Private input videos and generated full movie files are not inside this source ZIP. Test-manifest fixture paths refer to the development machine and must be adjusted before another machine reruns them. This is a functional, tested development release; it is not universal browser/hardware certification.
'''
(root/'HANDOFF.md').write_text(text)
p=root/'README.md';s=p.read_text();lines=s.splitlines();lines[0]='> Read **HANDOFF.md first** for the completed final half-SBS tests and remaining browser/hardware limits. Nothing has been published.';p.write_text('\n'.join(lines)+'\n')
summary=[dict(name=x['name'],settings=x['settings'],nativeBytes=x['native']['bytes'],wasmBytes=x['wasm']['bytes'],codedFrames=x['wasm']['frames'],durationSeconds=x['wasm']['duration'],nativePSNR=x['analysis']['native']['psnr'],wasmPSNR=x['analysis']['wasm']['psnr'],nativeSSIM=x['analysis']['native']['ssim'],wasmSSIM=x['analysis']['wasm']['ssim'],byteExact=x['bitExact'],audioPCMIdentical=x['audioParityPass'],qualityParityPass=x['qualityParityPass'],nativeSeconds=x['native']['elapsedSeconds'],wasmSeconds=x['wasm']['elapsedSeconds'],wasmHeapBytes=x['wasm']['peakCommandHeapBytes'])for x in rows]
(root/'dist/benchmarks.json').write_text(json.dumps(summary,indent=2))
