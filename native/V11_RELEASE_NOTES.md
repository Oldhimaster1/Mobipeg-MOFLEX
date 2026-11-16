# MobiPEG V11 — Decoder-Aware Motion / Texture Quality

**Status: experimental hardware candidate (November 16, 2026).**
MobiPEG independently encodes MOFLEX / Mobiclip video. V11 has passed
software decode checks; **V11 playback on an original Old 3DS remains untested**.

## Deliverables

- `Avatar_3D_MobiPEG_V11_DecoderAware.moflex`: complete 3D Avatar test
  trailer including the original V10 audio. Frame count: 4,826 coded frames
  (2,413 stereo pairs), 400 × 224 per eye, 24 fps per eye.
- `MobiPEG_V11_Full_Source_and_Encoder.zip`: complete patched FFmpeg and
  x264 source, tools, previous profiles, and the V11 offline encoder.
- `MobiPEG_V11_Charts_and_Test_Results.zip`: full-frame quality charts,
  all 300 new decoder-checked candidate results, packet rate, and investigation.

## Full-trailer metrics

All values below were computed over **all 4,826 frames** except the stated
SSIM / edge / grain sampling. Images were compared against the normalized
400 × 224 stereo-eye raw source. Higher PSNR/SSIM is better; lower errors
and block boundary artifact proxies are better.

| Metric | MobiPEG V10 | MobiPEG V11 | Change |
|---|---:|---:|---:|
| File size | 20,529,152 B | **20,508,672 B** | -20,480 B |
| Luma PSNR | 35.559 dB | **35.929 dB** | +0.370 dB |
| SSIM (sampled) | 0.94421 | **0.94864** | +0.00443 |
| Luma error at source edges | 66.214 | **61.406** | -7.26% |
| Static-area flicker error | 17.361 | **15.932** | -8.23% |
| After-scene-cut error | 21.962 | **20.201** | -8.02% |
| Source-relative 4×4 boundary excess | 1.110 | **0.960** | -13.56% |
| Peak video over a packet-aligned second | 2,782.6 kbps | **2,637.0 kbps** | -5.23% |

Nintendo's official reference is **20,588,544 B** total, so V11 is
**79,872 B smaller**. Nintendo's 4×4 boundary excess was **0.362** in a
240-frame sample versus V11's **0.960**, i.e. **V11 still has noticeably
more block boundary artifact potential**. Nintendo also maintained a
lower video peak (~1,978.8 kbps) and smoother per-second allocation.

**Important comparison caveat:** The official Nintendo output differs from
the normalized original source in frame timing and color/resizing.
Therefore, direct same-frame Nintendo-vs-source PSNR is **not a fair
ranking of subjective Nintendo versus MobiPEG quality**. Nintendo's video
is the perceptual quality target, but no parity claim is made.

## What changed technically

The old motion-vector search optimizes prediction using H.264 interpolation
rules. However, Nintendo/Mobiclip's decoder interpolates half-pel vectors
with different integer-rounding behavior. V11's encoder experiments with
nearby motion vectors using the **actual MobiClip predictor** during
encoding: `MOBI_V11_MV_REFINE=1` with adjustable change penalty. For each
~2-second GOP, it also tests finer quantization, decodes and measures each
candidate, and selects GOP settings under the baseline V10 video budget.
No new bitstream feature is introduced.

## Verification conducted

- 40 earlier candidate runs tested an experimental DC boundary rounding
  idea; **rejected** because it damaged fidelity. The flag is disabled.
- 35 motion-search proof-of-concept candidate runs, all decoder-verified.
- **300 additional V11 candidate GOP encodes with software decoder checks**;
  the selected full video passed complete video/audio decode.
- All 4,826 frames decoded again for full-reference assessment.
- Audio after decoding is bit-identical to V10 (SHA-256
  `14a5a360faaac1acc880db8bed1f73e4ce1c4b0738b839d37bf273212b86f34c`).
- Linux native FFmpeg/x264 patched encoder compiled and used successfully.
- Syntax-check of shipped Python scripts succeeded.

## What remains before an actual release

1. **Old 3DS hardware playback** of this exact V11 trailer in Nintendo
   3D Movie Viewer: test eye depth/order, scene cuts, audio sync, smoothness,
   and seek behavior. Software decoder success alone is insufficient.
2. Reduce 4×4 block boundary artifacts further, ideally without sacrificing
   fine detail. Match Nintendo's steadier bit allocation and peak bitrate.
3. Independent macOS/Windows/Linux source-build and full encode checks;
   the macOS build script is included but untested in this run.
4. Regression corpus across animation, high motion, shadows, flat color,
   low light, and both HSBS / FSBS stereo inputs. Capture real device feedback.

The new multi-pass encoder deliberately spends much more compute time than
a one-pass encode and has **no validated real-time fps claim**.
