# MobiPEG Studio V15 quick start

## Requirements

1. Python 3.9+ (Tkinter required only for graphical mode).
2. This package's **custom patched FFmpeg** encoder/ffprobe pair. Standard FFmpeg does not support the custom `mobiclip` encoder or `moflex` muxer.
3. On **Linux**, run `bash BUILD_FOR_LINUX.sh` from this directory to build its bundled sources (C compiler, make, pkg-config required). On **macOS**, review/use `BUILD_FOR_MAC.command` and build scripts. This release tested the Linux custom binary; native macOS/Windows binaries are **not** supplied or verified.
4. On Windows/MSYS2, compile the included patched FFmpeg and x264 sources for your own environment, then point `--ffmpeg` to the resulting executable. The Studio GUI/CLI itself runs on Windows, but **the encoder still needs a working custom Windows build**.

## Graphical interface

```bash
python3 MobiPEG_Studio_V15.py --gui
```

Select video, mode (2D, full-SBS, half-SBS), target resolution *per eye*, FPS, quality and output filename. Click **Convert and verify MOFLEX**. Detailed progress appears in the log. The converter runs in a worker thread to keep the window responsive.

## Command line

**Quality-focused 2D** (V15 motion refinement enabled automatically):

```bash
python3 MobiPEG_Studio_V15.py --input "anime.mp4" --mode 2d --preset quality --resolution 400x240 --fps 24
```

**True 3D, full side-by-side** (two distinct eyes):

```bash
python3 MobiPEG_Studio_V15.py --input "3D_movie.mp4" --mode full-sbs --preset quality --resolution 400x224 --fps 24
```

**Half-width side-by-side** source:

```bash
python3 MobiPEG_Studio_V15.py --input "3D_HSBS.mp4" --mode half-sbs --resolution 400x224 --fps 24
```

**Hard final file-size limit** (10 decimal MB):

```bash
python3 MobiPEG_Studio_V15.py -i "movie.mp4" --max-size-mb 10 --preset quality
```

**A/B encoder control:**

```bash
python3 MobiPEG_Studio_V15.py -i "movie.mp4" --motion-refinement off --output control.moflex
python3 MobiPEG_Studio_V15.py -i "movie.mp4" --motion-refinement on  --output V15.moflex
```

To select a custom binary, append `--ffmpeg /absolute/path/to/custom/ffmpeg`. Its sibling `ffprobe` must exist in the same directory. The scripts use `./local/bin/ffmpeg` automatically after a normal package build.

## Run tests

From this folder:

```bash
python3 -m unittest discover -s V15 -p 'test_studio.py' -v
python3 -m unittest discover -s V13 -p 'test_quant_plan.py' -v
python3 -m unittest discover -s V14 -p 'test_scene_cut_plan.py' -v
```

For the additional 20 seek/decode smoke probes, run `python3 V15/seek_smoke.py --help` and pass the three optional test videos, custom FFmpeg and a JSON report path.

The V15 live integration suite needs a working custom `./local/bin/ffmpeg`; in a workspace with legacy layouts it also supports `MobiPEG_V13_work/local/bin/ffmpeg`. Lab scripts in `V15/` are research reproduction scripts and expect the original named source videos or intermediates; see their headers and the separate evidence package. Experiments are not a single-command universal benchmark.

## Real 3DS release gates (not yet verified)

- Test complete **2D** and **3D** outputs on both Old 3DS and New 3DS.
- Verify left/right depth, no eye swap, audio sync and final seconds.
- Seek forward/backwards across hard cuts (especially Avatar title, underwater, and action).
- Check 15+ minutes of playback on SD, pauses, resume, and low-space cards.
- Check the hard-size-budget outputs and modes at 24/30fps.
- Do not label the experimental whole-trailer 3D build “stable” until its scene cuts and seeking pass on actual hardware.
