# MobiPEG FPS and cross-platform progress — November 15, 2026

This report covers new work on the **custom independent Mobiclip encoder**, not
Nintendo's encoder or the Clownsec Big Top client. The default high-quality
encoding recipe remains **QP12, subme9, skip0, hex, GOP60**.

## Speed-versus-quality measurement

Three independently preprocessed, real-world samples were used at 400×240,
YUV420p, 30000/1001 FPS; 120 frames per sample. The test compiled FFmpeg plus
the custom x264-derived Mobiclip encoder, using an Intel Xeon Platinum 8573C
Linux worker. These are **host measurements**, not an estimate of the
user's i7-7700HQ or any Mac. Results are medians of two independent encodes,
with a reversed-order second pass. PSNR compares complete decoded MOFLEX
frames to frame-aligned, preprocessed Y4M inputs.

| Sample | subme | Median encoding FPS | Decoded PSNR (dB) | MOFLEX bytes |
| --- | ---: | ---: | ---: | ---: |
| gottalove | 9 | 82.17 | 46.8094 | 466,944 |
| gottalove | 7 | 114.64 | 46.3291 | 622,592 |
| gottalove | 5 | 113.20 | 46.2111 | 532,480 |
| gottalove | 2 | 156.63 | 46.1870 | 425,984 |
| mariee | 9 | 79.98 | 50.2256 | 245,760 |
| mariee | 7 | 104.55 | 49.7926 | 319,488 |
| mariee | 5 | 102.10 | 49.5677 | 368,640 |
| mariee | 2 | 134.73 | 49.2793 | 204,800 |
| yu | 9 | 20.78 | 42.2425 | 3,207,168 |
| yu | 7 | 50.16 | 41.7036 | 3,440,640 |
| yu | 5 | 83.91 | 41.5470 | 2,437,120 |
| yu | 2 | 87.91 | 41.5060 | 2,314,240 |

**Conclusions:** On this three-clip workload, subme2 was approximately
1.7–4.2× faster than subme9. Subme9 consistently yielded the highest PSNR;
lower search effort is **not** a lossless optimization. Some faster outputs
are smaller, but not all (subme7 often increases size). File size by itself
cannot measure fidelity; no quality parity is implied. Never silently replace
subme9 with a faster setting. The new launchers preserve quality by default
and make `MOBIPEG_PROFILE=balanced|fast|fastest` an explicit choice.

## Quality-preserving encoder optimizations

1. **Whole-block Mobiclip motion compensation (experimental).** When all 16
   four-by-four luma cells have the same motion vector and reference index,
   the encoder can render one 16×16 luma and two 8×8 chroma blocks. When any
   cell differs, it falls back to the original sub-block predictor, preserving
   support for fine partitions and stereoscopic conversion. `MOBI_FAST_MC=1`
   enables this experiment; it is **off by default** until throughput is
   clearly positive across workloads. Eighteen A/B runs (three clips ×
   three repetitions × two modes) yielded byte-identical complete MOFLEX
   files for both paths. The combined median was **2.49% slower** with the
   fast path, despite isolated faster cases. That is NOT a validated speedup.
2. **Interpolation filter dispatch moved outside the pixel loop.** The
   four Mobiclip half-pel interpolation modes now run separate integer loops,
   and direct copies use `memcpy`. The exact rounding expressions are
   unchanged. Baseline and modified complete MOFLEX files matched byte for
   byte across 18 alternating A/B runs (three scenes × three repetitions ×
   two binaries). Median scene-level CPU FPS changes were +6.7%, −4.8% and
   +0.8%, respectively; the median scene-level change was **+0.76%**. This is
   neutral within observed variability and **not** a major FPS breakthrough.
3. **Vectorization is now enabled explicitly in native builders.** The
   bundled x264 `configure` historically appends `-fno-tree-vectorize`,
   overriding an earlier `-ftree-vectorize`. Build-only scripts replace that
   trailing opt-out; the production source remains portable C. Comparing a
   vector-enabled and vector-disabled Linux build yielded identical MOFLEX
   bytes for six matched encodes across three clips. Short-run FPS varied
   with host load, so **no guaranteed percent increase** is claimed.
4. **Native 16×16 SAD function (experimental).** Two manual 256-pixel SAD
   accumulations per inter macroblock can instead use the codec's existing
   `pixf.sad[PIXEL_16x16]`. `MOBI_FAST_SAD=1` enables that implementation;
   default is off. Eighteen same-binary alternating A/B runs were
   **byte-identical**, but the candidate was **2.00% slower** by the combined
   median FPS on this host. Do not enable it by default on the basis of these
   measurements.

### Static-area skip threshold

The `MOBI_SKIP` threshold is a separate fidelity tradeoff. Testing thresholds
128 and 512 at subme9 did **not** produce a repeatable speed gain. At 512,
decoded PSNR changed from 46.8094 to 46.5910 dB (`gottalove`), from 50.2256
to 50.1113 dB (`mariee`), and from 42.2425 to 42.2333 dB (`yu`). Leave
`MOBI_SKIP=0` for the quality reference.

## New multicore breakthrough: GOP-aligned work distribution

For quality-first subme9, the encoder still processes individual dependent
frames serially within a GOP. The existing multi-process tool can assign
**independent GOPs** to separate workers. We added a dedicated
`--seam-mode gop` that only splits at multiples of `--gop` (60 frames by
default), rejects incompatible `--chunk-frames`, and avoids unnecessary
per-pixel cut scoring. The user-facing multicore launcher now selects
60-frame GOPs instead of shifting boundaries toward nearby scene cuts.

| 360-frame sample | Method | End-to-end seconds | FPS including validation | Complete MOFLEX SHA-256 vs serial |
| --- | --- | ---: | ---: | --- |
| Repeated `yu` | 1 worker, three 120-frame chunks | 18.994 | 18.95 | Exact match |
| Repeated `yu` | 3 workers, three 120-frame chunks | 7.707 | 46.71 | Exact match |
| Three different source clips concatenated | Continuous 1-worker encoding (no tool overhead) | 6.858 | 52.49 | Reference |
| Three different source clips concatenated | 3 workers, scene splits at 120/240 | 6.138 | 58.65 | Exact match |
| Three different source clips concatenated | 3 workers, fixed 60-frame GOPs | 5.046 | 71.34 | Exact match |
| Three different source clips concatenated | 3 workers, new `gop` 60-frame mode | 4.716 | 76.34 | Exact match |

The repeated-`yu` worker-count comparison was **2.46× faster** using three
workers versus one with identical preparation/verification logic. All listed
exact-match results were verified with full-file `cmp` or SHA-256, and decoded
MD5 also matched. A separate 120-frame continuous-motion test split at frame
60 likewise matched the single-file output byte-for-byte.

**Negative control:** Splitting the mixed clip at non-GOP frame boundaries
90/180/270 produced **different compressed files**, as expected. Bit identity
at GOP boundaries is supported by these tests, **not yet proven for all video
sources, scenecut behavior, frame rates, audio, or 3D**. The utility still
reports `bit_exact_to_sequential: false` unless an external reference encode
was actually compared; that field is deliberately conservative. Mac and
3DS-hardware multicore playback are untested. Mismatched files may still look
and decode correctly, but cannot be claimed byte-identical.

## Build targets and realistic support boundaries

| Target | State in this source package |
| --- | --- |
| Linux x86_64 | New `BUILD_FOR_LINUX.sh` **compiled successfully** locally with GCC, make and pkg-config; full 120-frame 2D fast-profile and 120-frame synthetic full-SBS 3D fast-profile conversions passed final decode/frame-count checks |
| macOS Intel / Apple Silicon | Existing `BUILD_FOR_MAC.command` uses portable C and Apple Clang; no Mac hardware build verification yet |
| Windows | Prior modified FFmpeg binaries and experiments exist; this package is not a Windows installer |
| iOS | Plausible native cross-compilation path, but no iOS framework, signing, UI, or device build yet |
| Web browser / WebAssembly | Research target only; needs Emscripten toolchain, compatibility review, memory optimization and dedicated UI |

**Portability requirements:** Avoid `-march=skylake` in distributable
cross-platform scripts. Avoid hard-coded OS paths and GNU-only dependencies
where Apple/Clang differs. Document any GPL requirements for FFmpeg/libx264;
platform distribution has additional policies. Native encoder throughput must
be evaluated on each target CPU rather than inferred from host Xeon numbers.

## Test reproduction

Both benchmark programs accept Y4M inputs so decoding and high-quality
resizing are excluded from the timed encode. An example normalized fixture:

```sh
./local/bin/ffmpeg -hide_banner -y -i input.mp4 \
  -vf 'fps=30000/1001,scale=400:240:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,pad=400:240:(ow-iw)/2:(oh-ih)/2,format=yuv420p' \
  -frames:v 120 -an -f yuv4mpegpipe corpus/input.y4m

python3 tools/benchmark_quality_speed.py \
  --ffmpeg ./local/bin/ffmpeg --input-dir corpus \
  --output-dir quality_results --repeat 2 --subme 2 5 7 9

python3 tools/benchmark_motion_compensation.py \
  --ffmpeg ./local/bin/ffmpeg --input-dir corpus \
  --output-dir motion_results --repeat 3 --subme 9
```

The benchmark tools save machine-readable `runs.csv` and `summary.json`.
Neither program requires a paid service. **Original uploaded test videos are
not included** in the source distribution.

## Next engineering work

1. Use representative longer sequences and instruction-level profiling to
   find the high-quality subme9 bottleneck before accepting further changes.
2. Optimize per-block distortion/rate decision while retaining bit-exact
   output; reject gains that vanish under repeated alternating A/B tests.
3. Extend the GOP-parallel bit-exact trials to longer non-repeating videos,
   stereo 3D, audio remux, and scenes with internal keyframe decisions.
4. Validate on an Intel Mac, Apple Silicon Mac, the user's i7-7700HQ, and
   actual Old/New 3DS with 2D and 3D playback; stress long files and audio.
5. Only then tackle an iOS native library or WASM port. Plex client support
   is separate and currently not the focus.
