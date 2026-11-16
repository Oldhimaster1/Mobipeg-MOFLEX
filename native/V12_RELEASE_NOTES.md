# MobiPEG V12 — Smoothness and DetailGuard (November 16, 2026)

**EXPERIMENTAL.** Two complete Avatar 3D MOFLEX test files were built with
the independent MobiPEG encoder. Both decoded in software and are smaller
than Nintendo's official reference. Physical Old 3DS playback of these
exact two V12 files is **not yet verified**.

## The user-reported problem

Although V11 restored considerable source detail, its output still looked
grainy/rougher than Nintendo's official Mobiclip output. Measured on 240
representative coded eye frames, excess 4×4 block-boundary contrast was
0.960 for V11 versus 0.362 for Nintendo. Excess energy in source-flat
areas was 0.7184 for V11 versus 0.6174 for Nintendo.

## What changed in V12

- After generating V11's decoder-aware motion GOPs, a new optional stage
  tests **edge-preserving bilateral** and mild HQDN3D **spatial-only**
  filtering, plus combinations with a slightly finer quantizer.
- Every candidate is decoded and compared to the *unfiltered* source.
  The bitrate controller chooses the best variant scene-by-scene within a
  measured total video budget; Nintendo's commercial encoder is not used.
- **No temporal filter is applied across interleaved 3D eyes.** That would
  mix left/right frames and damage the stereoscopic image.
- Balanced/DetailGuard applies tighter quality guards. SmoothFocus allows
  slightly more deviation from source when that measurably reduces grain.
- A separate high-frequency AC deadzone hypothesis (`MOBI_V12_HF_DZ`) was
  tested and rejected: it sometimes increased block-boundary artifacts.
  The flag remains present in source for research but is disabled in V12.

## Measured results — entire Avatar trailer

4,826 decoded coded frames, 2,413 stereo pairs, 400×224 per eye, 24 fps per
eye. Full-frame PSNR and error metrics use the normalized original input,
not Nintendo's differently preprocessed encode.

| Metric | V11 | V12 DetailGuard | V12 SmoothFocus |
|---|---:|---:|---:|
| Complete MOFLEX file size | 20,508,672 B | 20,529,152 B | 20,533,248 B |
| Luma PSNR | 35.9289 dB | 35.9518 dB | **35.9266 dB** |
| Source-flat grain proxy | 0.71844 | 0.69971 | **0.66892** |
| 4×4 boundary excess | 0.95987 | 0.93709 | **0.92126** |
| Static-scene flicker error | 15.932 | 15.646 | **15.095** |
| Sampled SSIM | 0.94864 | 0.94816 | 0.94693 |
| Source-edge MSE | 61.406 | 61.064 | 61.668 |
| After-scene-cut MSE | 20.201 | 20.321 | 20.330 |
| Peak video bitrate / packet-aligned second | 2,637 kbps | 2,652 kbps | 2,701 kbps |

**SmoothFocus vs V11:** 6.9% lower grain proxy, 4.0% lower block-boundary
excess, 5.3% lower static flicker, and effectively unchanged luma PSNR
(-0.0023 dB). It trades some SSIM and slightly raises peak bitrate.

Nintendo's reference file is **20,588,544 B**, so V12 SmoothFocus remains
55,296 B smaller and V12 DetailGuard 59,392 B smaller. Nintendo's measured
source-flat grain proxy is 0.6174; SmoothFocus has reduced the V11-to-Nintendo
gap in this single proxy by roughly half. Nintendo's boundary artifact proxy
is still considerably lower than both V12 profiles, so **the quality is not
equal to Nintendo**.

The reference Nintendo file uses different temporal preprocessing/resizing
and sometimes maps to an adjacent stereo-eye frame relative to our normalized
source. Direct Nintendo-vs-source PSNR is not a fair subjective ranking.
The grain and block numbers are uncalibrated *proxies*, not proof of how a
particular scene looks on a handheld LCD.

## Tests

- 400 full-trailer V12 GOP candidates, each with decoder verification.
- 35 stronger-bilateral pilot candidates, 48 filter/quantizer pilot
  candidates, 30 initial smoothing candidates, and 36 coefficient candidates
  before selecting the final approach.
- Every final file decoded again: **4,826 / 4,826 coded frames each**.
- Audio decoding identical across V11, DetailGuard and SmoothFocus:
  `14a5a360faaac1acc880db8bed1f73e4ce1c4b0738b839d37bf273212b86f34c`.
- Native Linux encoder rebuilt successfully with bundled source.
- Python source syntax checks and packaged script CLI smoke tests passed.
- ZIP archives passed archive integrity tests.

## Hardware test checklist

1. Load **SmoothFocus** first with Nintendo 3D Movie Viewer on Old 3DS.
2. Compare against **DetailGuard** and the **V11** sample for grain,
   readability of foliage/skin/water, stereo depth, and motion smoothness.
3. Check the first frame, cuts, seek, both eyes, audio sync, and full playback.
4. If hardware playback stutters, share the timestamp. The 2,701 kbps peak
   is higher than Nintendo's ~1,979 kbps peak, though total sizes match.

## Cross-platform source

The archive contains patched full FFmpeg/x264 code, the independent MOFLEX
encoder, V9/V10/V11/V12 multi-pass Python quality tools, Linux build script,
and macOS build / encode `.command` scripts. macOS is **source-build-ready
in theory, not actually compiled/tested on a Mac in this run**. System FFmpeg
with `bilateral` and `hqdn3d` filters is additionally needed. The multi-pass
quality path is deliberately slow, not a real-time 200-fps path.
