# MobiPEG V5 — Bit-budget-matched stereoscopic 3D research build

**Status:** experiment validated by software decoding; **awaiting Old 3DS hardware test** for this specific optimized file. The earlier 70 MB interleaved Avatar test passed hardware playback. The previous side-by-side layout-4 output did not.

## Important results — full Avatar trailer

| Result | Original Nintendo reference | V4 fixed-quantizer, segmented | V5 adaptive, size-matched |
|---|---:|---:|---:|
| Full MOFLEX bytes | 20,588,544 | 20,815,872 | **20,570,112** |
| Video packet payload bytes | 15,926,292 | 16,058,385 | **15,813,777** |
| Coded stereo eye frames | 4,826 | 4,826 | 4,826 |
| Per-eye geometry | 400×224 | 400×224 | 400×224 |
| Display stereoscopic FPS | 24 per eye | 24 per eye | 24 per eye |
| Audio codec | Stereo MOFLEX ADPCM | Stereo MOFLEX ADPCM | Stereo MOFLEX ADPCM |
| Entire file decode | Pass | Pass | Pass |
| Old 3DS hardware playback | User-produced official reference | Not yet tested | **Not yet tested** |

**V5 is 18,432 bytes (0.090%) smaller than Nintendo's 1-pass 20.59 MB reference.** It is also 245,760 bytes smaller than V4's segmented QYX4 baseline. The much earlier QYX2 70 MB output is a *different quality/bitrate point*, not the comparable baseline.

## Objective quality on an identical normalized MobiPEG input

V4 segmented uniform QYX4 (QP12, subme9) to V5 matched-size adaptive:
- Full-frame luma PSNR: **34.6319 → 34.6669 dB** (+0.035 dB).
- Sampling-based luma SSIM: **~0.9345 → ~0.9354** in the full second-pass audit. Sampling details are in `per_eye_full_decoded_metrics.csv`.
- The first-pass GOP sample metrics used for selecting quantizers show **~0.9354 → ~0.9365**, a different but consistently sampled subset.
- These improvements are small but positive while the total file is smaller.

These measurements compare *MobiPEG codecs on the same input*, so they can support an A/B conclusion. **They do not prove parity with Nintendo's image quality.** Nintendo's proprietary resizer and color-processing differ from our Lanczos source normalization. Full-trailer SSIM on that chosen reference was higher for official Nintendo video (~0.954) than for V5 (~0.935), despite Nintendo's luma PSNR being lower. Visual side-by-side comparisons suggest there are still differences in edge/textural reconstruction. Reproducing Nintendo's detail at exactly the same file size remains an engineering target.

## Algorithm actually implemented

A **measured two-stage, GOP-level rate-distortion controller**, not a claim that we recreated Nintendo's internal 2-pass codec:
1. Split 24 Hz stereo source into alternating 400×224 left/right coded eye frames at 48 coded FPS.
2. Divide into 2-second **GOP-aligned** chunks (96 coded frames; last chunk has 26).
3. Independently encode each chunk with five MobiClip quantizer phase/tier settings using independent, modified FFmpeg/x264 **without running Nintendo binaries**.
4. Fully decode and score every candidate against identical normalized raw frames (MSE, PSNR and sampled SSIM); record actual video packet bytes.
5. Solve a constrained multiple-choice dynamic-programming problem to choose one candidate per chunk under the video payload budget. Protect against major GOP-level fidelity regressions.
6. Concatenate **compressed packets** (not decoded footage), preserving exact segment reconstruction. Mux original stereo audio as MOFLEX ADPCM and write the correct interleaved-3D descriptor at 24 FPS per eye.

Tested **285 complete segment encode/decode trials** across quantizer configurations (255 selected candidate combinations for 51 chunks, plus 30 additional preliminary candidates), with 4,826 coded eye frames in the completed file.

## Hardware and software validation

- Original V4 correct interleaved layout: user confirmed successful playback on an original 3DS.
- V5: all 4,826 coded eye frames software-decode with strict error handling.
- Full V5 decoded frame hash **exactly** matches concatenation of the independently decoded selected GOP chunks.
- Both eye images are retained and the proper left-first interleave descriptor is present.
- ADPCM decodes 4,433,920 stereo samples at 44.1 kHz = 100.5424 seconds. Stereo movie duration from 4,826 coded frames / 48 = 100.5417 seconds (difference under 1 ms).
- Both video and audio streams and all packets validated. **3DS hardware and seeking have not been tested for this new adaptive version.**

## Reproduce (Linux/macOS, patched MobiPEG build required)

Dependencies: Python 3, NumPy, scikit-image and a normal FFmpeg build for source decoding. Bundled MobiPEG FFmpeg must include `mobiclip` encoder, `moflex` muxer, `concat` and `s16le` demuxers, and `-mo_interleave_input_double_rate` support (new in V5).

From the V5 source package root, run:

```bash
python3 -m pip install numpy scikit-image
bash BUILD_FOR_LINUX.sh  # or BUILD_FOR_MAC.command on macOS
python3 V5/encode_stereo_v5.py 'video_HSBS.mp4' --ffmpeg local/bin/ffmpeg --ffprobe local/bin/ffprobe --video-kbps 1266.5 --workers 4
```

For the exact Avatar official file-size match, instead of the default 1266.5 kbps, use the low-level `V5/adaptive_stereo.py` command with `--target-video-bytes 15822090 --perceptual-weight 0.5` after `V5/normalize_stereo.py`. This adjusts for the specific MOFLEX audio/mux overhead; the initial video bitrate is not exactly the final file size.

On Windows, `V5_ENCODE_STEREO.cmd` works **after** a V5-enabled Windows FFmpeg/MobiPEG build is available. The package contains source, not a precompiled/validated Windows binary. Do not run the old standard V4 binary with these new flags.

## Known remaining issues

- A different film and input aspect ratio need independent tests of the allocation policy.
- No full-length feature film stress test of this controller yet.
- Nintendo's codec still has unmatched edge/prediction behavior; the quality gap is not solved by GOP bit allocation alone.
- Nintendo installer materials and proprietary DLLs are **not included** in this package.
- Windows, macOS, Old3DS hardware seek and adaptive stereo playback still require independent verification.
