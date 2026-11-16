# MobiPEG V12 — smoothness/detail experiment

This version adds an optional source-aware, **spatial-only** treatment to the
V11 decoder-exact motion encoder. It tests edge-preserving bilateral and
conservative HQDN3D spatial denoising with optional finer quantization.
All candidates are decoded and scored against the original **unfiltered**
pixel source, not against the treated input. A bitrate optimizer selects the
version of each scene that improves smoothness without exceeding per-scene
source fidelity guards.

Use `--smoothness-profile balanced` (default) for stronger source-detail
guards, or `--smoothness-profile smooth` to prioritize grain and block
suppression at some additional source-fidelity cost. Neither profile is proven
to match Nintendo's perceptual quality; compare on the real Old 3DS.

Unlike temporal filtering, the spatial filters do not mix alternate stereo
eye frames. Mixing the two 3D eyes would create ghosts and incorrect depth.

## Linux

Install system FFmpeg/ffprobe including the `bilateral` and `hqdn3d` filters,
compiler/build tools, Python 3, NumPy, SciPy, and scikit-image. From the
top-level extracted directory:

```bash
bash BUILD_FOR_LINUX.sh
python3 V12/encode_stereo_v12.py '/path/to/3d_hsbs.mp4' \
  --encoder local/bin/ffmpeg --probe local/bin/ffprobe \
  --workers 5
```

## macOS

Install Xcode Command Line Tools, Homebrew FFmpeg and pkgconf and the Python
dependencies. Double-click `BUILD_FOR_MAC.command`, then
`ENCODE_3D_V12_SMOOTH_DETAIL.command`. A true native Mac build/test has **not**
been carried out in this investigation.

## Research flag not selected

`MOBI_V12_HF_DZ` in the patched x264 source is an opt-in experimental
coefficient-level suppression. The trial found unstable block-boundary
behavior, so the V12 wrapper leaves this disabled. It is included only
to reproduce the research.

## Limitations

- Very slow compared to a one-pass encode; this is an offline research profile.
- Not the licensed Nintendo encoder; no equivalence to Nintendo's output is
  claimed.
- Hardware validation on Old 3DS in Nintendo 3D Movie Viewer is necessary.
- Recommended to compare V11 and V12 on hardware side by side, especially
  grain, skin texture, foliage, shadows, and fast cuts.
