# MobiPEG release-candidate reliability, color and speed lab

Date: 2026-11-15. Status: **experimental developer preview; not yet a stable hardware-qualified release**.

## Outcome

- **418 actual software checks** across **14 MOFLEX files** (eight color-safe real uploads,
  five previously generated 2D/3D regression fixtures, and one official Nintendo cancan MOFLEX).
- **415/418 checks passed (99.28% of this specific test matrix)**. This is a test-case
  proportion, **not** an estimate of real-world reliability or crash probability.
- **224/224 randomized direct seeks passed** with the new experimental *accurate rewind*
  demuxer patch. It deliberately seeks from the start and decodes forward, and is therefore
  slow for long content. This fixes this FFmpeg demuxer's result, **not** necessarily a
  native 3DS player's independent seek implementation.
- **14/14 complete video decodes**, **12/12 complete audio decodes**, **56/56
  decoded-frame hashes stable over thread counts 1/2/4/8**, **56/56 remuxes with
  identical compressed video payloads**.
- **39/42 intentionally damaged MOFLEX files rejected by strict decoding**. The
  three uncaught cases removed exactly the final 4 KiB media block and lost only a
  trailing audio packet: the front index proves all video frames are still present,
  but contains no authoritative audio sample count or checksum.
- **33/33 file-integrity checks passed** for the new eight-video package (eight intact
  checksums, 24 deliberately modified byte streams detected, one complete ZIP CRC).
  Shipping/checking the SHA256SUMS file is required: successful decoding does
  **not** prove an audio-complete file.
- **18/18 available Python unit cases passed** across the existing smart-fast
  and QualitySafe stereoscopic regression suites; three additional smart-fast
  tests were skipped because their historical hard-coded research binaries/
  fixtures were not present. Skipped tests are not counted as passed.
- **Color-corrected one full-range MOV**: source-normalized PSNR-Y
  **31.78 -> 40.73 dB**, SSIM-Y **0.96363 -> 0.98689**, full MOFLEX file
  **3,121,152 -> 2,830,336 bytes** (9.32% smaller). All seven
  limited-range video sources produced **identical normalized YUV pixels** when
  the new explicit TV-range conversion was enabled.
- **GCC Skylake vectorized x264** preserved **identical complete compressed
  MOFLEX bytes for all eight 90-frame benchmark clips** relative to
  the original non-vectorized x264 build. On the research Xeon, interleaved
  A/B/B/A runs at one worker showed **+22.12% FPS**; at four
  concurrent workers only **+1.59% FPS**. Gains diminish at high concurrency.

## Software test breakdown

| Test | Passed | Total | Notes |
|:--|--:|--:|:--|
| Video layout/codec descriptors | 14 | 14 | 2D 400x240, stereo 800x240 |
| Entire video decode | 14 | 14 | Strict FFmpeg error mode |
| Entire audio decode | 12 | 12 | Two 3D samples intentionally silent |
| Decoded-frame checksums across 1/2/4/8 threads | 56 | 56 | Identical actual decoded pixels |
| Repeated MOFLEX remux, compressed-packet hashes | 56 | 56 | No re-encoding of video |
| Damaged-file rejection | 39 | 42 | Three truncated audio tails accepted |
| Random direct seeks with experimental rewind | 224 | 224 | Fast arbitrary-keyframe seek not solved |
| **Total software tests** | **415** | **418** | **3 remaining fail-fast gaps** |
| Separate package SHA/ZIP integrity | 33 | 33 | Catches missing audio tail bytes |

The sample fixtures and precise per-case outcomes are in
`release_lab_results/reliability_test_results.json`.

### What changed in the demuxer

The original `moflex_read_seek()` simply returned `-1` with no
reinitialization, leaving generic seeking capable of starting a P-frame
without the reference-picture history and producing `setup_qtables failed`.
The patch now:

1. Rewinds the seekable input to offset zero and clears accumulated packet,
   PTS, and block state, allowing FFmpeg's accurate-seek layer to decode/discard
   frames to the requested timestamp.
2. Reads the existing MobiPEG front index's declared frame count only when the
   front data table matches the expected 16+24*n schema. Incomplete **video**
   content can no longer be silently treated as clean EOF for that schema.
3. Leaves arbitrary vendor data-stream formats uninterpreted rather than
   guessing fields from them.

Apply only to the matching MobiPEG FFmpeg source:

```bash
cd /path/to/mobipeg
patch -p1 < /path/to/moflex_seek_integrity_experimental.patch
```

The exact patch was verified with `patch --dry-run -p1` against the user's
uploaded MobiPEG source snapshot. A real Windows recompile and physical 3DS
validation have not happened.

### Color/range correction

The seven normal uploaded files are tagged limited/TV range. Only
`Video by pallavi.mehrra.mov` is tagged full/PC range. Explicit FFmpeg
source normalization is:

```
fps=30,scale=400:240:force_original_aspect_ratio=decrease:force_divisible_by=2:in_range=auto:out_range=tv:flags=lanczos,pad=400:240:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p
```

This changes actual luma sample values **only when required by the source's
range metadata**. Do not apply a speculative global -4 YUV offset. The new
color-safe pack contains the corrected file and all seven original
limited-range outputs unchanged.

Full-file source-referenced PSNR/SSIM scores for all eight files are in
`SOURCE_QUALITY_SCORES.json`. The source is normalized to the **same**
400x240, 30fps yuv420p image geometry as the encoder: it measures codec loss
at that target resolution, not fidelity to the original high-resolution
video. A human side-by-side and actual 3DS screen remain useful.

## Measured encoding speed

Eight **independent** 90-frame, 400x240 Y4M clips (720 total frames per sweep)
were encoded at **exactly** QP12 / subme9 / skip0 / GOP60 / hex, with
identical input frames across builds.

| Research Xeon workers | Original GCC FPS, mean of 2 | Skylake-vector GCC FPS, mean of 2 |
|--:|--:|--:|
| 1 | 54.75 | 66.69 |
| 2 | 86.65 | 104.87 |
| 4 | 118.75 | 128.57 |
| 8 | 156.29 | 148.34 |

Because concurrent speed results varied, a more controlled alternating
**baseline, vector, vector, baseline** experiment measured:

| Worker count | Baseline | Vector | Gain |
|--:|--:|--:|--:|
| 1 | 51.589 FPS | 63.003 FPS | **+22.12%** |
| 4 | 123.459 FPS | 125.422 FPS | **+1.59%** |

Complete MOFLEX SHA-256 outputs matched between builds for all eight clips
and all worker counts. The optimized x264 was compiled with GCC using
`-O3 -march=skylake -ftree-vectorize -funroll-loops`, not an
incompatible 4-slice native-thread experiment. The build uses **no x264
assembly** and still needs a Windows x64 compile for the user's machine.

The test CPU was a **Xeon Platinum 8573C**, **not** the user's Intel
Core i7-7700HQ. Throughput here measures multiple *different clips
encoded concurrently*; it is not single-stream frame-threading.
Previously measured Windows throughput remained **5.87 FPS**
for 1,697 frames, 4 workers, QP12. **100 FPS on Windows has
not been demonstrated.**

## Release blockers and decisions

### P0: required before claiming a supported Windows/3DS public beta

1. Real playback on the **Old 3DS and New 3DS XL**, plus Azahar:
   all eight 2D clips and full-/half-SBS 3D samples; stereo slider 0/50/100%,
   correct left/right eye mapping, 30fps playback, loop/end behavior, audio sync.
2. Full seeking tests on a real 3DS player, including 3D and long media.
   The FFmpeg fix is exact but slow: a genuine indexed keyframe seek remains
   engineering work.
3. Build the modified FFmpeg and patched x264 **for Windows x64**,
   verify its executable, reproduce quality/speed scores on the
   i7-7700HQ, and include hashes, source commits, licenses, and rollback.
4. Validate mono, no-audio, VFR, rotated phones, 23.976/24/25/29.97/30/59.94
   fps, multi-hour inputs, seek-offset overflow, cancellation/cleanup, and
   disk/memory pressure.
5. Always publish/check an external SHA-256 manifest because the existing
   MOFLEX front table does not prove the audio tail is complete.

### P1: needed for a stable general release

- Real master-MP4 comparisons at *matched bitrate* vs Nintendo's
  proprietary MobiClip output. The original `cancan.mp4` master was not
  provided; pixel/size similarity alone cannot prove superior codec
  efficiency.
- Confirm BT.601/BT.709 color metadata, chroma siting, and TV/PC range
  across more mobile sources and both stereo eyes.
- A portable quality-preserving Windows optimization build and benchmarks.
  Do not promise 100 FPS based on this separate Xeon.
- Stable GUI options, progress and ETA, audio-end checks, and high-quality
  versus experimental faster modes with clear warnings.

### Release recommendation

**Ship the current work only as a clearly labeled developer preview.**
After hardware acceptance and native Windows test/packaging, a public
beta may be appropriate. An unrestricted stable release should wait for
long-content, fast seeking and more source-matched quality evidence.

The FFmpeg build links x264, so any binary distribution must properly
address GPL source and license obligations. See
https://ffmpeg.org/legal.html and https://ffmpeg.org/general.html .

## Reproduction files in this package

- `moflex_seek_integrity_experimental.patch` — independently dry-run verified.
- `release_reliability_lab.py` — complete decode, remux, 224 seeks, corruption.
- `bench_parallel_mobipeg.py` / `repeat_vector_abba.py` — full speed sweeps.
- `color_range_regression.py` / `score_conversions.py` — pixel-range and PSNR/SSIM.
- `verify_release_manifest.py` — SHA256 + ZIP negative integrity tests.
- `results/` — raw machine-readable outcomes for inspection.

All software tests use MobiPEG's own custom encoder/decoder; **no Nintendo
proprietary encoder was used to create any new MOFLEX output**.
