# MobiPEG V7 — Stereo-aware measured rate control (research release)

**Status:** Real 3D MOFLEX created and software validated, **not yet validated on an Old 3DS**. This is an experimental improvement over V5, not a claim of Nintendo-equivalent subjective quality.

## What changed

- Preserves MobiPEG's independent MobiClip encoder, **400×224 per eye, 24 stereo pairs/s**, ImageLayout 0 (interleaved left/right eye packets); no Nintendo proprietary libraries.
- Native x264/MobiClip mode-analysis lambda offset switch `MOBI_RDO_LAMBDA_DELTA`; default zero preserves old bitstream behavior; V7 evaluates offsets `0` and `2` experimentally. This tunes actual *mode decisions*, not the displayed frame rate or container layout.
- Stereo-aware adaptive rate controller in `V7/adaptive_stereo_v7.py`, now evaluating **both left and right eyes** for sampled SSIM, plus edge error, scene-change onset error, and low-quality GOP constraints.
- Uses a measured quality/bytes constrained optimizer to assign one of 10 trial settings per independent stereo GOP (5 quantizer configurations × 2 mode-analysis lambda variants).
- Includes normalized-raw cache verification (source SHA256 + preprocessing parameters); changes cannot silently reuse another video's frames.
- Includes **optional**, unverified per-eye crop-before-scale normalization and configurable Lanczos/bicubic/bilinear/area/spline scaling; V7 tested Avatar still uses V5's classical preprocessing.
- The alternative 4×4 prediction-cost estimator is included in C source as an **opt-in experiment only**, disabled by default: 18 tests produced byte-identical output, so no quality gain was proven for that path.

## Exact full-length Avatar A/B measurements

All numeric image-quality measurements here compare against the **same V5-normalized source**. This is an *internal V5→V7 comparison*; Nintendo uses different image preprocessing, so measurements are not directly codec-to-codec equivalent.

| Metric | V5 | V7 |
|:--|--:|--:|
| Complete stereo file size | 20,570,112 B | **20,578,304 B** |
| Stereo coded eye frames | 4,826 | **4,826** |
| Source-referenced luma PSNR | 34.6669 dB | **34.7345 dB** |
| Left-eye PSNR | 34.7266 dB | **34.7967 dB** |
| Right-eye PSNR | 34.6080 dB | **34.6733 dB** |
| 5th-percentile individual-frame PSNR | 31.0920 dB | **31.2260 dB** |
| Sampled left+right SSIM | 0.935405 | **0.935980** |
| Source-edge MSE (GOP measurements) | 69.490 | **68.332** |
| Post-scene-cut luma MSE | 26.691 | **26.144** |
| ADPCM stereo decoded PCM SHA256 | 14a5a360... | **identical** |

Nintendo original Avatar is **20,588,544 bytes**, so V7 is **10,240 bytes smaller (0.0497%)**. Stereo duration, resolution, audio, and all 4,826 coded packets were validated. The original V5 was 18,432 bytes smaller than Nintendo; V7 trades an extra 8,192 bytes for modest objective fidelity improvements.

**This improvement is not huge.** It's a small, independently measured compression improvement. Visible blocking/grain at scene changes may still occur. Qualifying a release on real hardware and measuring side-by-side subjectively remain necessary.

## Research and tests

- 18 C 4×4 prediction-mode cost policy A/B encodes: **all byte-identical**, no improvement proven.
- 78 short video encode/decode lambda-offset trials with detailed PSNR/size measurements. Delta=2 modestly improved pooled rate-distortion at fixed quantization; no universal guarantee.
- 285 original V5 GOP candidates + 285 new lambda-offset GOP candidate encodes = **570 measured 2-second candidates**; every new candidate strictly decoded and measured for both eyes.
- 51 GOPs selected within the same total **15,813,777-byte video payload budget** as V5. Chosen V7 video payload **15,810,029 bytes**.
- Full 100.54 s stereoscopic video and audio decoded successfully, with 4,826 stereo eye frames, matching reconstructed GOPs byte for byte and audio PCM matching V5.
- Other source scales and a short two-GOP CLI dry-run tested. Windows and macOS builds and hardware playback of V7 **not tested in this environment**.

## Running the encoder

The source archive does **not** include proprietary Nintendo executables, downloaded movie content, or prebuilt cross-platform FFmpeg binaries. Build the bundled patched encoder for your own OS, then run the experimental V7 pipeline:

### Linux (from the package root)

```bash
python3 -m pip install numpy scikit-image
MOBIPEG_BUILD_JOBS=4 bash BUILD_FOR_LINUX.sh
bash V7_LATEST_STEREO.command 'your_movie_H-SBS.mp4' --workers 4 --video-kbps 1266.5
```

### macOS (Intel or Apple Silicon)

```bash
python3 -m pip install numpy scikit-image
bash BUILD_FOR_MAC.command
bash V7_LATEST_STEREO.command 'your_movie_H-SBS.mp4' --workers 4 --video-kbps 1266.5
```

Both platform compilation procedures are supplied as source scripts; the **V7 clean full build is not yet qualified** for release on all platforms. The Linux test executable was rebuilt successfully against V7 patches within the research test environment, not via the packaged clean-build script (which has only partially completed).

### Windows

The batch launcher `V7_LATEST_STEREO.cmd` is included, but you must first build a Windows FFmpeg containing the patched custom MobiClip encoder and MOFLEX muxer and put `ffmpeg.exe` and `ffprobe.exe` in `local\bin`. **This ZIP is source-only, not a ready-to-run Windows program**.

### Output, time and disk requirements

The controller first produces an alternating-eye YUV420p source, then encodes **10 settings per GOP**, decodes trial files to score both eyes, selects the combination under the requested video bitrate, and muxes final video and stereo ADPCM. This is much slower and heavier on disk/CPU than a single-pass encode. Expect at least several GB of temporary space for feature-length source footage. Output location: `<source_stem>_MobiPEG_V7/MobiPEG_V7_STEREO_3D.moflex`.

Use `--max-gops 2` for a source smoke test (no final assembled output), or `--normalize per-eye` only to experiment with crop-first scaling (not used in V7's measured baseline). `--official path/to/reference.moflex` sets video payload budget exactly to the reference, but no official file is required.

## Remaining known issues / release blockers

1. V7's full video **still needs actual original Nintendo 3DS hardware playback** including 3D depth, seek, audio sync and scene transitions; successful software decoding is not proof.
2. Compression gains are modest; **Nintendo's scene placement, texture rendition and temporal bit-budget smoothing are not fully reverse engineered**.
3. GOP duration remains 2 seconds with max keyint 48 coded frames, so forced I-frame frequency is still much higher than Nintendo's (V5: 165 vs Nintendo 44 for this reference). Lengthening GOP requires careful seeking and Old3DS testing.
4. No guarantee that source content is H-SBS unless supplied by the user. Automatic SBS format detection, general F-SBS, 2D, audio-less sources and mobile/web binaries should be treated as future work for V7 pipeline.
5. Two-pass all-candidate quality optimization is resource-intensive, not a realtime streaming encoder.

The baseline V5 source remains included and unchanged as an alternative within the package.
