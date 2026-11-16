# MobiPEG independent MOFLEX encoder — V4 performance engineering

November 15, 2026. 3DS-compatible **custom** encoder source, not Nintendo's
proprietary Mobiclip compiler. Linux Xeon Platinum 8573C host; the Mac build
is included as portable source but has NOT been executed on macOS hardware.

## What consumed CPU time?

`MOBI_PROFILE=1` enables opt-in instrumentation in `encoder/encoder.c` and
`encoder/analyse.c`. It uses monotonic clock timings at macroblock level and
prints stage totals when encoding finishes. Disabled by default.

Representative 120-frame, 400x240, 45,000-macroblock hard-motion sample,
original QP12/subme9/skip0 settings:

| Stage | Time (ms) | Portion |
|---|---:|---:|
| Analysis | 3746.68 | 81.0% |
| Entropy coding | 577.86 | 12.5% |
| Macroblock encode | 282.04 | 6.1% |
| Cache preparation | 18.07 | 0.4% |
| **Total sampled** | **4624.66** | **100%** |

Inside analysis, `intra_rd_refine` consumed 2367.5 ms; it ranked/rate-distortion
encoded alternative predictions for 38,146 of the sample's macroblocks.
Theoretical Amdahl limit from eliminating that stage *entirely*:

`max_singlecore_speedup = 1 / (1 - 2367.5 / 4624.66) ≈ 2.05x`.

This demonstrates why 200 FPS on every high-motion clip cannot be delivered
simply by optimizing one hot loop. Separate GOPs can, however, run in parallel.

## New search shortcuts (all opt-in)

The untouched full-quality reference is the default:

`MOBI_INTRA_RD_CAP=0` (works regardless of `MOBI_INTRA_RD_POLICY`).

To shortlist expensive four-by-four intra prediction modes, use:

- `MOBI_INTRA_RD_CAP=3 MOBI_INTRA_RD_POLICY=1`: rank legal *Mobiclip-accurate*
  prediction directions by SATD and run expensive RD on the best three.
  **Recommended experimental mode** when speed matters more than bit identity.
- `MOBI_INTRA_RD_CAP=3 MOBI_INTRA_RD_POLICY=0`: original first-best plus two
  enum-order candidates; generally faster but its quality/size impact is worse.
- `MOBI_INTRA_RD_CAP=3 MOBI_INTRA_RD_POLICY=2`: rank using SAD (cheaper than
  SATD); a third experimental option, not the recommended default.

The environment values are read by the Mobiclip-specific x264 encoder only.
`MOBI_INTRA_RD_CAP=0` preserves full original candidate enumeration, and a
120-frame full MOFLEX output had the exact pre-patch SHA-256 digest.

## At least 102 independent short-clip conversions

Three separately normalized real video samples, 120 frames per sample, 400x240
YUV420p, all encoded and **fully decoded** for source-aligned PSNR:

- 42 cheap-shortlist tests: seven caps × three samples × two repetitions.
- 30 SATD-shortlist tests: five caps × three samples × two repetitions.
- 30 SAD-shortlist tests: five caps × three samples × two repetitions.

Second-pass cap enumeration was reversed to reduce systematic order effects.
The full machine-readable data is in the evidence folder of the source package.

| Clip | Reference FPS | SATD cap3 FPS | Ref PSNR (dB) | Cap3 PSNR (dB) | Ref bytes | Cap3 bytes |
|---|---:|---:|---:|---:|---:|---:|
| gottalove | 89.16 | 111.07 | 46.8094 | 46.6382 | 466,944 | 487,424 |
| mariee | 102.44 | 106.96 | 50.2256 | 50.1832 | 245,760 | 249,856 |
| yu (hard) | 24.37 | 30.36 | 42.2425 | 42.0365 | 3,207,168 | 3,137,536 |

These are medians of two encodes and may vary with background load. Full
encoded files do decode successfully. SATD cap3 has a small but **real**
fidelity tradeoff; it is not a lossless acceleration. The original remains
the standard for publication-quality encodes.

A separate **120-frame synthetic stereo full-SBS** check ran with cap3 and
four GOP workers: 800×240 video, MOFLEX layout 4, all 120 frames completely
decoded and MD5 validated, final packet SHA verified. Total throughput was
75.90 FPS including validation (102.83 FPS encode-only). This verifies
stereo file structure and decoder acceptance, **not physical 3DS playback**.

## Long GOP-parallel tests

The full 720-frame tests use 12 GOP-aligned 60-frame chunks, eight workers,
QP12/subme9/skip0, decoded frame MD5, compressed packet hashes, correct MOFLEX
layout and complete end-to-end validation.

| 720-frame source | Search | Encode-only FPS | Entire pipeline FPS | Total seconds |
|---|---|---:|---:|---:|
| Repeated hard `yu` | V3 original | 110.5 | 67.87 | 10.609 |
| Repeated hard `yu` | V4 full-quality | 111.91 | 73.04 | 9.858 |
| Repeated hard `yu` | V4 SATD cap3 | 139.64 | 89.85 | 8.013 |
| Repeated easier `gottalove` | V4 SATD cap3 | **396.91** | **233.69** | **3.081** |

Quality-mode full 720-frame MOFLEX files produced by V3 and V4 were
**byte-for-byte identical** (SHA-256:
`9d8fd0ba119fe76af15c22a7bd3d2ff9f4e8c67d6503ef4ed8db822920e32f02`).
The V4 multicore helper dispatches final independent decode/frame-count
verification concurrently and elides a redundant rehash after a byte copy.
Both original V3 and V4 still perform full stream validation. Host load affects
short wall-clock comparisons; speed differences are not a universal guarantee.

## Larger real-world batch

See `Nine-video COMPARISON_REPORT.md` and its CSV and dashboard delivered
separately. It uses nine full-length sources (not just the 120-frame benchmark
samples) and measures each source in both quality and turbo modes, including
audio, full-decode checks, packet hashes and source-aligned decoded PSNR.

## Reproducing the Turbo preset

On an Intel/Apple Silicon Mac after building the local source with
`BUILD_FOR_MAC.command`, double-click
`ENCODE_2D_RD_TURBO_EXPERIMENTAL.command` or
`ENCODE_MULTICORE_RD_TURBO_EXPERIMENTAL.command`. Standard `ENCODE_2D.command`
and `ENCODE_MULTICORE_EXPERIMENTAL.command` retain the original full RD search.
For more worker processes on a sufficiently capable machine, set
`MOBIPEG_JOBS=8` before launching multicore encoding.

On Linux, build with `BUILD_FOR_LINUX.sh`; the same two launchers invoke bash
and Python, though macOS Finder/`osascript` file-selection is Mac-specific.

No 3DS hardware test was performed on the newly accelerated cap3 bitstreams.
Earlier full-quality custom MOFLEX outputs played on real 3DS hardware.
Stereo playback, long-duration audio synchronisation, Intel/Apple Silicon
build behavior, and perceptual quality should be confirmed before a public
stable release.
