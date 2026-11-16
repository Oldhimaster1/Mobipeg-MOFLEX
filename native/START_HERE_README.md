# Our custom MobiPEG — Linux / macOS developer preview

**For Linux computers, Intel Macs and Apple Silicon Macs.** This ZIP contains the **modified MobiPEG encoder source** we've been testing, not the ordinary official GitHub release. It has the patched x264 backend, color-range-safe conversion, 2D MOFLEX, full-/half-SBS 3D MOFLEX, an experimental demuxer seek correction, scene-aware optional multicore encoding, and a **new experimental incremental MOFLEX muxer and Plex HTTP bridge**. The work now prioritizes native encoder speed and portability, not Big Top integration.

**Important:** This is a *source-build* package, not a precompiled Mac binary. The actual modified executable is built **locally on your Mac** the first time. We have successfully built/tested its Linux counterpart, but **we have not yet run this particular Mac build**. It is not hardware-qualified as a final 3DS release.

**November 15 V4 speed update:** The custom encoder now includes opt-in
intra-4x4 refinement shortlisting and a concurrently validated multicore
pipeline. Read `FPS_PERFORMANCE_REPORT_V4.md` for the complete profiling,
102-shot three-algorithm experiment, full-quality regression hashes, and 720-
frame stress results. The default `ENCODE_2D.command` and
`ENCODE_MULTICORE_EXPERIMENTAL.command` retain exhaustive search quality.
`ENCODE_2D_RD_TURBO_EXPERIMENTAL.command` and
`ENCODE_MULTICORE_RD_TURBO_EXPERIMENTAL.command` explicitly enable the faster
SATD top-three search. This turbo option **changes the bitstream and slightly
reduces measured PSNR**; do not mistake it for a lossless acceleration. Neither
the V4 Mac binary nor these accelerated outputs are hardware-qualified yet.

## 1. Build once on your Mac

1. Unzip the archive and keep the entire `MobiPEG_Custom_Mac_Preview` folder together.
2. Install Apple's Xcode Command Line Tools if not already installed: open Terminal and run `xcode-select --install`.
3. Install `pkgconf` (pkg-config), e.g. `brew install pkgconf` if you use [Homebrew](https://brew.sh).
4. Open Terminal, type `bash ` (including a trailing space), **drag `BUILD_FOR_MAC.command` into Terminal**, and press Return. Or double-click the `.command` file if permitted by macOS.
5. Wait for the two C projects to compile. Build speed depends on the Mac; it can take several minutes. The compiled encoder goes in `local/bin/ffmpeg` and `local/bin/ffprobe`.

Build prerequisites: Xcode Command Line Tools / Apple Clang, `make`, and `pkg-config`. **No Nintendo SDK, Nintendo encoder, Python package installation, or paid license.** Python 3 is needed for the experimental multicore and live Plex HTTP launchers; no pip dependencies.

If an older build already exists and you want to rebuild it, run `MOBIPEG_REBUILD=1 bash BUILD_FOR_MAC.command` in Terminal. You may set `MOBIPEG_BUILD_JOBS=2` on low-memory Macs.

## 2. Encode a video

- **2D:** Double-click `ENCODE_2D.command` and choose the input video. Or drag the video onto this `.command` file, if your macOS configuration permits.
- **Full SBS stereo 3D:** `ENCODE_3D_FULL_SBS.command`, for SBS where each eye is naturally full-width.
- **Half SBS stereo 3D:** `ENCODE_3D_HALF_SBS.command`, for anamorphic half-width left/right images.
- **Experimental multicore:** `ENCODE_MULTICORE_EXPERIMENTAL.command`. This now splits at exact 60-frame GOP boundaries and runs independent workers. On several real-source tests this delivered bit-identical MOFLEX and up to 2.46× end-to-end speedup at three workers, but other sources can still yield different frames or seams. Requires Python 3. It is not native within-GOP frame threading.

The saved `.moflex` appears **next to your input video**, using a name such as `movie_MobiPEG_2D.moflex`. Existing files are not overwritten. The script encodes at 400x240 per eye, 30000/1001 FPS, QP12, subme9, skip0, hex motion estimation, GOP60; converts full-range video to TV-range when indicated; converts audio to MOFLEX ADPCM; then decodes the entire output to check for errors. Output frame count is verified.

Run `SELF_TEST.command` to check the built encoder on generated synthetic frames before converting personal videos. Run `REALTIME_30FPS_CHECK.command` to benchmark 300 synthetic frames at high-quality QP12 and see if that Mac is anywhere near real-time processing.

If macOS blocks a `.command` file from opening, run it via Terminal (`bash /path/to/file.command`); follow your Mac's normal app-security settings. Do **not** globally disable Gatekeeper.

### Linux build (GCC)

On Debian/Ubuntu-based distributions install `build-essential` and `pkg-config` (use your distribution's equivalent elsewhere). Then:

```sh
bash BUILD_FOR_LINUX.sh
bash encode_macos.sh 2d /path/to/video.mp4
MOBIPEG_PROFILE=fast bash encode_macos.sh 2d /path/to/video.mp4
MOBIPEG_PROFILE=fast bash encode_macos.sh full-sbs /path/to/full_sbs.mp4
```

Despite its original filename, `encode_macos.sh` also supports command-line input on Linux. The private binaries are in `local/bin/` and are built from the **bundled custom source**. `MOBIPEG_BUILD_JOBS=8` adjusts compile parallelism and `MOBIPEG_REBUILD=1` forces a rebuild. This is a source-build package, not a Linux distro-native installer.

### Choose speed or quality intentionally

| Profile | Mobiclip search depth | What it means |
| --- | --- | --- |
| `quality` (default) | subme9 | **Highest PSNR** of the tested modes; matches our previously hardware-playable high-quality settings |
| `balanced` | subme7 | Faster search, some measurable PSNR loss; may increase file size |
| `fast` | subme5 | Much faster for complex motion; measurable PSNR loss |
| `fastest` | subme2 | Often fastest, may visibly reduce detail in difficult scenes |

All profiles preserve QP12, skip0, 400×240 per eye, the original color pipeline and GOP60. On a Mac, double-click `ENCODE_BALANCED.command` or `ENCODE_FAST.command` for 2D, or use `MOBIPEG_PROFILE=fast bash encode_macos.sh half-sbs your_video.mp4` for 3D. Faster presets change encoded pixels and are **not** a bit-identical replacement for `quality`. See [FPS_PORTABILITY_REPORT_V3.md](FPS_PORTABILITY_REPORT_V3.md) for measured FPS, PSNR, file sizes, and a quality-preserving GOP-parallel benchmark.

## 3. Hardware warning / reporting bugs

3D is experimental until checked on an **actual Nintendo 3DS**: left/right eye assignment, 3D slider, audio continuity, final frame, playback/seek behavior, and old vs new 3DS. Successful FFmpeg decoding does not establish hardware playback.

**Plex streaming is partially implemented and still experimental.** Our new `-mo_live 1` muxer emits video/audio blocks progressively without waiting for the end of the movie, and `START_PLEX_LIVE.command` serves this as HTTP chunked data. It can resolve a Plex library item, but **current Clownsec Big Top 3DS clients cannot play an unknown-length live feed**: they require a completed seekable file, a known Content-Length and Range requests. Actual Old/New 3DS playback also needs client changes and hardware validation. See `PLEX_REALTIME_STREAMING_ROADMAP.md`.

## 4. Experimental live bridge — computer playback proof only

First build the Mac encoder. In Terminal:

```sh
# Local video proof of concept (press Ctrl+C to stop the HTTP server):
bash START_PLEX_LIVE.command /path/to/video.mp4 --seconds 10

# Instead, use a Plex library ratingKey with your OWN server's token:
# Keep the token out of scripts, screenshots and shared files.
export PLEX_TOKEN='YOUR_PLEX_TOKEN'
bash START_PLEX_LIVE.command --rating-key 1234 --plex-base http://127.0.0.1:32400
```

From a second Terminal, read and save the 10-second preview:

```sh
curl --fail http://127.0.0.1:32550/health
curl --fail http://127.0.0.1:32550/live.moflex -o live_test.moflex
./local/bin/ffmpeg -v error -xerror -i live_test.moflex -f null -
```

`--mode full-sbs` or `--mode half-sbs` accepts stereoscopic side-by-side input. Defaults: QP12/subme9/skip0, 400×240 per eye, 30000/1001fps. Use `--fps 15` as an explicit CPU/temporal-fidelity tradeoff if the host cannot reach 30 fps. The bridge uses `-re`, so it will not output faster than source playback; **actual real-time viewing additionally requires the encoder to sustain the desired output fps**. Output is **unindexed** and intended for a future *live-capable homebrew receiver*, not the regular downloaded-file player. Binding `--host 0.0.0.0` exposes your video over the LAN; default loopback is private.

For bug reports, please send the Terminal output, macOS version, Mac chip (`uname -m`), whether the source had audio, and the generated `.moflex` if possible. A matching test video helps reproduce quality and speed differences.

## 5. Our modifications and evidence

- **x264:** The provided modified x264 source is the same source used in our November 15 test builds. The earlier Xeon speed-up used GCC-specific `-march=skylake` vectorization, which **cannot run on Apple Silicon**. The Mac builder instead uses portable Clang vectorization on the C-only x264 path. **Mac FPS and bit-identical output are unmeasured** until someone builds and benchmarks it.
- **New source-level speed experiments:** The portable interpolation refactor preserved byte-identical MOFLEX files in three scenes; an optional uniform-MV motion-compensation path (`MOBI_FAST_MC=1`) also preserved bytes but failed to show consistent speedup and is off by default. Linux/macOS builders explicitly prevent x264's configure script from disabling requested compiler vectorization. No per-platform FPS claim is made without a local benchmark.
- **FFmpeg:** Original uploaded MobiPEG source plus our validated `moflex_seek_integrity_experimental.patch` applied to `libavformat/moflex.c`. The fix preserves packet history by rewinding for accurate seeking, which is correct but can be slow on long clips; it also checks the declared video frame count against truncated streams.
- **Video pipeline:** Corrects source `full`/`limited` color-range handling via explicit `in_range=auto:out_range=tv`. High-quality settings intentionally preserve the QP12/subme9 reference.
- **Multicore:** Uses independently encoded source segments and scene-aware seam selection. It is NOT native MobiClip frame threading and is NOT guaranteed byte-identical to sequential output.
- **Incremental MOFLEX:** `-mo_live 1` writes interleaved video and ADPCM as encoding progresses. The original indexed writer remains the **default** (`-mo_live 0`); these modes were compared using decoded frame/PCM hashes. The live writer deliberately omits the final front-of-file seek table and is **not** a drop-in format for a seek-based 3DS playback API.
- **Software audit:** See `ENGINEERING_TEST_REPORT.md` for the previously completed 418-case reliability study, quality and benchmark results. Those are **Linux research results, not a Mac validation**.

## 6. Licenses and sources

This package contains the complete modified FFmpeg/MobiPEG and x264 source trees under `source/`, including their license files. FFmpeg's GPL configuration and the x264 code are subject to their respective open-source licenses; share source and attribution whenever you redistribute builds. Original projects: https://github.com/quatric/mobipeg and https://github.com/quatric/x264; original FFmpeg: https://ffmpeg.org/.

The separate *official* MobiPEG v3.0 macOS release is **not** included; it is a different binary/code line from this custom experimental build. Our research preview is not an endorsement or product release by the upstream authors.

## 7. File integrity

`SHA256SUMS.txt` records hashes of all packaged project files, including sources. On macOS, from the extracted project directory:

```sh
shasum -a 256 -c SHA256SUMS.txt
```

The installed `local/` and temporary `.build/` are generated after first run and are not part of the original archive or its hashes.
