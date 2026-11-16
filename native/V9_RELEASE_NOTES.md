# MobiPEG V9 — texture guard and original-file-size result

**Status: experimental. Old 3DS hardware playback of this exact V9 sample is
pending user verification.**

## Avatar 3D HSBS full-video test

Controlled test: the same source, normalized to 400x224 YUV420P with two
alternating eyes (4,826 coded frames, 2,413 stereo pairs). Independently
decoded and checked all video frames; decoded ADPCM PCM audio SHA-256 matches
the prior V8 artifact exactly. Nintendo's original supplied MOFLEX is the
size reference, not the training input.

| Metric | MobiPEG V8 | MobiPEG V9 peak-capped | Change |
|:--|--:|--:|--:|
| Total MOFLEX bytes | 20,570,112 | **20,553,728** | -16,384 bytes |
| Official Nintendo MOFLEX bytes | 20,588,544 | **20,588,544** | V9 -34,816 bytes |
| Video packet payload bytes | — | 15,778,797 | Per-packet checked |
| Luma PSNR (dB) | 34.89467 | **34.90185** | +0.00718 dB |
| Sampled 7x7 SSIM | 0.935104 | **0.935675** | +0.000571 |
| High-frequency energy in source-flat areas | 0.794027 | **0.768531** | **-3.21%** |
| Static-region flicker error (MSE) | 20.070375 | **19.217259** | **-4.25%** |
| Source-edge MSE (lower is better) | **76.11916** | 76.49806 | +0.50% (regression) |
| After-scene-cut MSE | 25.24619 | **25.17319** | -0.29% |
| 5th percentile luma PSNR (dB) | 31.25929 | **31.27590** | +0.01661 dB |
| Worst 1-second video payload (kbps) | 2,896.912 | **2,889.040** | -0.27% |

**Important:** This is a modest but reproducible improvement, NOT the large
visual leap or Nintendo equivalence we ultimately want. The edge-error
regression and remaining visible blockiness require further R-D and motion
compensation research. The flat-region grain and flicker values are
source-masked proxies, not direct subjective quality scores. The 7x7 SSIM
implementation differs from V8's original scikit-image test methodology;
this table was computed for both files under the *same* V9 audit method.
Nintendo's differently processed stream does not align with the normalized
source for straightforward pixelwise PSNR rankings; do not interpret the
absolute Nintendo-source PSNR as an encoder-quality ranking.

## Verification performed

- **500 decoder-verified GOP candidate encodes** across 50 regions, with
  the exact variants, quantizers, decisions and measurements preserved.
- 42 regions chose new texture/flat-region quantizer modes; eight regions
  stayed on V8-compatible baseline settings.
- All **4,826 coded stereo-eye frames** decodable; video packet count and
  payload sums checked; no decoder errors for this built file.
- ADPCM stream successfully decoded, and audio PCM hash matched V8 exactly.
- Complete video was scored using PSNR, sampled SSIM, source-edge error,
  source-flat grain proxy, source-relative temporal flicker and scene cuts.
- A per-second payload-rate cap guarded new GOP variants, and an independent
  whole-file audit verified a lower peak than V8.
- Linux native patched FFmpeg/x264 build succeeded. macOS and physical
  Old 3DS need user-side validation of this particular V9 output.

## What to test on Old 3DS next

1. Open `Avatar_3D_MobiPEG_V9_PeakCapped.moflex` in **Nintendo 3D Movie
   Viewer** (not Clownsec Player).
2. Check stereo eye order, depth and screen geometry with the 3D slider.
3. Watch the fast jungle, water, and scene-change sequences for blockiness,
   grain, stutters or catch-up buffering; compare against V8 and Nintendo.
4. Check audio starts promptly and remains synchronized.

If V9 still looks worse than Nintendo, retain the official test video, and
focus future R-D work on reconstruction at cuts, motion-vector choices and
blockiness, while holding the same payload budget and frame-rate ceiling.

## Files

- `Avatar_3D_MobiPEG_V9_PeakCapped.moflex`: main Old 3DS test candidate.
- `MobiPEG_V9_Full_Source_and_Encoder.zip`: portable source, build scripts,
  generic HSBS/FSBS V9 wrapper, and analysis scripts.
- `MobiPEG_V9_Charts_and_Test_Results.zip`: full-video charts/JSON, verified
  500 GOP trials and initial sweep results.
