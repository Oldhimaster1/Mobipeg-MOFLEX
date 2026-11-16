# MobiPEG V9: experimental 3D texture and scene-quality encoder

This is the **full independently developed MobiPEG source-based encoder** for
Nintendo 3DS MobiClip/MOFLEX, extending V8. No Nintendo Mobiclip commercial
encoder executable or proprietary runtime is bundled.

## What's actually new

- A source-level predictive-luma quantization correction in
  `source/x264/encoder/macroblock.h`. The original 4x4 path used the intra
  quantization offset even on predictive blocks. V9 exposes the missing inter
  offset *only when requested* through `MOBI_V9_INTER_LUMA_DZ=1`.
- A 4x4 **source-variance guard** (`MOBI_V9_INTER_FLAT_RANGE`) applies that
  offset preferentially to flat regions, preventing unnecessary loss at
  stronger edges. V8 default output remains unchanged when the new flags
  are unset.
- A measured, decoded GOP-by-GOP rate/distortion search. Each candidate is
  encoded, decoded, inspected for errors, scored for PSNR, SSIM, source-edge
  error, high-frequency grain, transitions, and temporal flicker. A size
  constrained optimizer selects the profile per section.
- Optional per-GOP one-second packet-rate ceiling via `--peak-1s-kbps`,
  plus a cache fingerprint so different videos cannot accidentally reuse
  stale comparison data.

## Linux setup

Requirements: C compiler, `make`, `pkg-config`, system `ffmpeg` and `ffprobe`,
Python 3, `numpy`, `scipy`, and `scikit-image`.

```bash
python3 -m pip install numpy scipy scikit-image
bash BUILD_FOR_LINUX.sh

python3 V9/encode_stereo_v9.py '/path/to/3D_HSBS_movie.mp4' \
  --encoder local/bin/ffmpeg --probe local/bin/ffprobe \
  --profile texture --video-kbps 1266.5 --workers 5
```

## macOS setup

Install the Apple Command Line Tools with `xcode-select --install`, and make
sure system `ffmpeg`, `pkg-config`, Python 3 and its packages above are
available. Homebrew users can run `brew install ffmpeg pkgconf python`.

1. Double-click `BUILD_FOR_MAC.command` to compile the source for your Mac.
2. Double-click `ENCODE_3D_V9_TEXTURE.command` and select your 3D video.
3. Copy the resulting `.moflex` to the 3DS SD card.

The bundled Linux build was tested in this environment. The macOS build is
supplied as source and build instructions, but has **not** been validated on
physical macOS hardware during this run.

## More control

```bash
python3 V9/encode_stereo_v9.py movie_HSBS.mp4 \
  --encoder local/bin/ffmpeg --probe local/bin/ffprobe \
  --video-kbps 1266.5 --profile texture \
  --peak-1s-kbps 2897 --workers 5
```

The 2,897 kbps ceiling here is the measured **Avatar V8 reference peak**,
not a universal 3DS bitrate requirement. Other video content may need a
different limit. All rates target video packet payload; MOFLEX headers and
ADPCM audio add size. The full rate-cap check is GOP-local, so verify the
final entire file's per-second packet peaks independently if necessary.

The standalone `v9_full_reencode.py` can re-run a finished V8 selection,
and `v9_texture_sweep.py` and `v9_full_quality_audit.py` provide metric
tools. Full sweep and audit artifacts are in the companion test-results ZIP.

## Scope and compatibility

This profile is for **2-eye half/full side-by-side 3D** input. Normalization
generates alternating 400x224 left/right eye frames at 48 coded fps for
24 fps per eye, MOFLEX layout 0. Stereo display should be verified with
**Nintendo 3D Movie Viewer on an Old 3DS**, including slider depth, cuts,
smoothness and audio sync. Successful PC decoding does **not** certify
hardware playback. Quality scores are relative to the normalized source,
and alone do not establish parity with Nintendo's encoder.

The V9 patch and scripts can be modified and redistributed in accordance
with the licenses of the bundled FFmpeg, x264, and other source components;
consult the upstream license files in `source/`.
