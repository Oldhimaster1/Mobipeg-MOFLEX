# MobiPEG V14 CutGuard — 2026-11-16

Experimental Mobiclip/MOFLEX encoder research, with safe quality preservation
and source-fidelity-focused bitrate allocation around genuine scene cuts.

## Results on the user-provided Avatar 3D teaser

All MobiPEG numbers are measured against the same independently normalized
400×224-per-eye source. The Nintendo file used different source preparation;
its PSNR is deliberately not used as a quality reference.

| Full video | File bytes | Luma PSNR | Sampled SSIM | After-cut MSE | Edge MSE | Worst 5% PSNR |
|---|---:|---:|---:|---:|---:|---:|
| Nintendo official | 20,588,544 | not comparable | not comparable | not comparable | not comparable | not comparable |
| MobiPEG V12 SmoothFocus | 20,533,248 | 35.926585 | 0.946926 | 20.330253 | 61.667607 | 31.719324 |
| MobiPEG V13 Quality | 20,570,112 | 36.075062 | 0.948233 | 18.832839 | 58.644134 | 31.989617 |
| **V14 Safe (recommended)** | **20,570,112** | **36.083328** | **0.949105** | **17.830482** | **57.020166** | **31.982088** |
| V14 CutFocus | 20,578,304 | 36.080931 | 0.949404 | 17.380376 | 56.344777 | 31.884132 |

V14 Safe improves post-cut MSE by **5.32% over V13** and **12.30% over V12**,
without increasing V13's full file size. CutFocus improves after-cut MSE by
**7.71% over V13** and **14.51% over V12**, while staying 10,240 bytes below
Nintendo's file. Its worst-frame percentile is somewhat lower than V13's,
so the recommended default is Safe.

These improvements are measurable but do not establish visual parity with the
official Nintendo encoder, especially on dark gradients and title screens.

The test trailer uses 4,826 alternating coded left/right eye frames at 48
coded frames/s (24 fps/eye), source display resolution 400×224 per eye,
and 44.1-kHz stereo ADPCM. Software decoding of both final V14 versions
completed for all 4,826 coded frames. Decoded audio PCM was identical to V12/V13
(17,735,680 bytes, SHA-256
`14a5a360faaac1acc880db8bed1f73e4ce1c4b0738b839d37bf273212b86f34c`).
Measured peak 1-second video bitrate remained 2701.392 kbps.

**Real Old Nintendo 3DS playback has not yet been verified for V14.** The
source was built and validated on Linux; macOS build support is included but
has not been tested in this iteration.

## What changed

- V13's custom x264 encoder supports opt-in real per-coded-frame Mobiclip
  quantizers through the `MOBI_V13_Q_PLAN` environment variable. This modifies
  QYX tier, per-frame QP remainder, emitted headers and reconstruction in lockstep.
  Without a plan, the original V12 control GOPs and complete 3D trailer were
  reproduced byte-for-byte.
- V14 adds **true cut-aware allocation**: detect same-eye scene changes,
  temporarily preserve more residual detail after the cut, and recover bits
  from safely low-motion intervals. Quantizer changes are always paired across
  left/right coded frames.
- We corrected a prior research limitation: the V9–V13 per-GOP `cut_mse`
  measured GOP beginnings, not arbitrary scene cuts. V14 scores all actual
  detected cuts separately, including those in the middle of a GOP.
- A strict per-GOP quality guard prevents a scene-cut improvement from being
  funded by excessively degrading an unrelated difficult scene.
- Keyframe forcing was tested at the single missed-I cut. It increased error
  in that already-nearly-exactly-predicted transition, and was rejected.

## Tests

- **600** full decoded GOP trials in the V13 adaptive-quantizer sweep.
- **209** additional decoded GOP trials focused on 22 real detected cuts
  across 19 GOPs.
- **6** forced-keyframe experiments (negative result, excluded).
- **3** V13 decoder-to-encoder reconstruction dumps matched byte-for-byte.
- **5** V13 quantizer-generator unit tests and **6** V14 scene-cut unit tests.
- Full-trailer V12 control reproduced byte-for-byte, SHA-256
  `e5d59fd97117b37275fb8d7f462fa57471a847e943593fedd127355ed8887bf9`.
- Both promoted V14 output movies decoded completely, verified stereo audio,
  used valid container packets, and remained smaller than Nintendo's reference.
- Independent full-trailer audits scored luma/chroma quality, sampled SSIM,
  edges, static flicker, grain proxy, actual scene-cut recovery, worst-frame
  PSNR and one-second video bitrate.

## Build and use the encoder

Use `BUILD_FOR_LINUX.sh` on Linux or `BUILD_FOR_MAC.command` on macOS.
Builds are local and preserve the bundled, modified x264 and FFmpeg sources.

`V13/plan_from_raw.py` creates a basic paired-eye adaptive quantizer plan
from planar YUV420p. `V14/scene_cut_plan.py` can refine a plan around detected
scene changes. Pass the resulting newline-separated integer plan to the patched
encoder using `MOBI_V13_Q_PLAN=/path/plan.txt`.

An *actual* V14-sized result needs trial encodes and a bitrate budget: merely
generating a Q plan does not guarantee any desired file size. The final Avatar
files were selected using constrained multi-GOP optimization and independent
decode measurements. Arbitrary 2D/3D video has not been validated to achieve
the same numerical gains.

This is experimental software under the license terms of its bundled sources.
