# MobiPEG V11 — decoder-aware half-pixel motion search

Experimental 3D MobiClip/MOFLEX encoder, without Nintendo's proprietary
commercial encoder. This package includes patched FFmpeg/x264 source code,
V7/V8/V9/V10 quality tools, the V11 encoder wrapper, and test scripts.

## What's new compared with V10?

The existing encoder's motion search uses an H.264 interpolation model.
MobiClip uses different half-pixel reconstruction rules (including integer
rounding). A motion vector which looks optimal during x264's original search
can therefore produce a worse decoded MobiClip prediction.

V11 introduces an **opt-in local post-search** for uniformly predicted
16x16 P macroblocks (`MOBI_V11_MV_REFINE=1`) that tests neighboring half-pixel
vectors using *the actual MobiClip interpolation*. The coder retains the best
prediction after a configurable motion-change penalty, then encodes residuals
normally. Only encoder decisions change; no decoder extension is necessary.

`MOBI_V11_MV_PENALTY` controls the search's resistance to a different
vector. The R-D controller evaluates several settings in each region,
alongside finer quantization settings. It encodes and decodes candidates,
measures image quality, and chooses a bounded-size final configuration.

The rejected `MOBI_V11_DC_MATCH` research flag is also in the source but
**off by default**: tests found its block-boundary gain was too small for
the loss of source fidelity. It is not selected by the V11 encoder.

## Linux

Install GCC or Clang, `make`, `pkg-config`, system FFmpeg/ffprobe, Python 3,
`numpy`, `scipy`, and `scikit-image`.

```bash
python3 -m pip install numpy scipy scikit-image
bash BUILD_FOR_LINUX.sh
python3 V11/encode_stereo_v11.py '/path/to/3D_HSBS_movie.mp4' \
  --encoder local/bin/ffmpeg --probe local/bin/ffprobe \
  --video-kbps 1266.5 --workers 5
```

## macOS

Install Xcode Command Line Tools, Homebrew FFmpeg/pkgconf and the Python
dependencies listed above. Double-click `BUILD_FOR_MAC.command` to compile,
then `ENCODE_3D_V11_DECODERAWARE.command` to select the movie.

The modified encoder was compiled and tested on Linux. This exact V11 source
has **not been built on a physical Mac** in this run.

## Bitrate and performance

- Inputs: H-SBS or F-SBS MP4/MKV video with audio.
- Output: 3D alternating-eye MOFLEX, 400x224 pixels per eye, 24 fps/eye.
- Quality search: many independent encoding and decoder-verification passes;
  substantially slower than a single-pass video encoder. This is *not*
  a benchmark for real-time encoding fps.
- `--peak-1s-kbps` optionally limits new GOP variants. The complete output
  should also be audited for burst bitrate.
- `--skip-v10` reuses a previously verified baseline in the output folder.

Physical hardware test is required on an Old 3DS using **Nintendo 3D Movie
Viewer**, particularly motion fluidity and stereo depth. Successful software
decode is not proof of official hardware compatibility.

The source includes FFmpeg/x264 under their accompanying upstream licenses;
follow those licenses when redistributing it or compiled builds.
