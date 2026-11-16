# MobiPEG V10 — motion and detail recovery (experimental)

V10 is the high-quality, 3D-focused encoder built on our standalone
MobiClip/MOFLEX source. It is **not** Nintendo's proprietary encoder, and it
does not require a commercial Mobiclip executable.

## Major V10 change

In `source/x264/encoder/macroblock.c`, the previous stabilization path snapped
a motion-compensated block's motion vector to zero when its estimated motion
gain was modest. This often threw away useful motion vectors, especially in
the alternating-left/right-eye stereo stream. That hypothesis is supported by
measured lower residual size and improved decoded image quality when the
snap is disabled, but still needs a hardware playback check.

Set `MOBI_V10_MV_SNAP=0` to preserve the motion search result. When omitted,
the old V9 behavior remains unchanged. A second optional experiment in
`macroblock.h` (`MOBI_V10_ACTIVITY=1`) changes only AC rounding decisions
based on the source 4x4 block's local activity. All these settings produce
normal, independently decodable MobiClip packets; there are no decoder changes.

The `v10_full_reencode.py` quality controller tests six opt-in choices per
section: preserved motion vectors, source-activity protection, and finer
quantizer phases/scales. It decodes and scores every candidate; its global
rate/distortion selector reinvests the recovered bitrate in fine details,
respecting the V9 video budget and a specified per-GOP payload peak cap.

## Linux

Requirements: a C toolchain and `make`, `pkg-config`, system `ffmpeg` and
`ffprobe`, Python 3 with `numpy`, `scipy`, and `scikit-image`.

```bash
python3 -m pip install numpy scipy scikit-image
bash BUILD_FOR_LINUX.sh
python3 V10/encode_stereo_v10.py '/path/to/3D_HSBS_movie.mp4' \
  --encoder local/bin/ffmpeg --probe local/bin/ffprobe \
  --video-kbps 1266.5 --workers 5
```

## macOS

Install Apple's Command Line Tools (`xcode-select --install`), Python 3,
FFmpeg, pkg-config and the Python packages above. With Homebrew:

```bash
brew install ffmpeg pkgconf python
python3 -m pip install numpy scipy scikit-image
```

Double-click `BUILD_FOR_MAC.command` to compile from source, then double-click
`ENCODE_3D_V10_MOTIONDETAIL.command` to choose a 3D input video.

The encoder was compiled and exercised on **Linux** in this run. The macOS
build is provided as portable source, but the specific V10 macOS build has
not been tested on an actual Mac.

For a subsequent run against a prevalidated V9 profile, the wrapper accepts
`--skip-v9`. For Old 3DS playback ceilings, set e.g.
`--peak-1s-kbps 2897`; that number is only the Avatar V9 reference peak,
not a general hardware standard. V10's local peak check does not replace
a full-file packet-burst audit.

## What to expect

- Input: half- or full-side-by-side 3D MP4/MKV, 2 eyes.
- Output: stereo-interleaved MOFLEX, 400x224 pixels per eye, nominal 24 fps
  per eye, ADPCM audio when the source provides audio.
- Quality mode: computationally intensive (the V9 and V10 candidate searches
  both involve hundreds of full encoder/decoder passes).
- Physical Old 3DS validation is **pending** for this V10 sample. Use
  Nintendo 3D Movie Viewer and test 3D order, audio sync, cuts, heavy scenes,
  and smooth playback before a production release.

## Reproducibility

The companion results ZIP contains all 300 V10 decoded candidate records,
the exact chosen 50-section plan, the complete 4,826-frame audit, and charts.
The V10 source archive contains the custom FFmpeg/x264 sources, V8/V9 tools,
and the V10 scripts. Observe the FFmpeg and x264 upstream licenses when
distributing modified source/binaries.
