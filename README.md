# MobiPEG

Convert videos to MobiClip video in `.moflex` containers for Nintendo 3DS playback. MobiPEG includes a desktop interface, command-line tools, and an optional browser app, built around modified FFmpeg and x264 sources.

## Features

- **2D and stereoscopic 3D:** convert ordinary videos or full- and half-side-by-side stereo sources.
- **Quality and size controls:** choose a quality preset, image cleanup filter, motion refinement, and an optional maximum output size.
- **3DS-sized output:** select 400×240, 400×224, or 320×240 per eye, with integer and fractional frame rates.
- **Audio conversion and verification:** convert audio to MOFLEX ADPCM and check the completed output by decoding it.
- **Local processing:** use the native tools on your computer or convert in a browser without uploading your video.

3D conversion requires a source with separate left and right views; it does not generate depth from a 2D video.

## Use on your computer

The native tools provide a Python graphical interface and a command-line converter. Build the bundled encoder first; an ordinary FFmpeg installation cannot replace this project's modified encoder and muxer.

Clone or download this repository, then run the following commands from its root.

### 1. Build the encoder

**Linux:** install your distribution's build tools, including GCC, make, and pkg-config, then run:

```sh
bash native/BUILD_FOR_LINUX.sh
```

**macOS:** install Xcode Command Line Tools, make, and pkg-config, then run:

```sh
bash native/BUILD_FOR_MAC.command
```

Both scripts install the encoder and matching `ffprobe` into `native/local/bin/`. Linux builds are covered by the included reports; the macOS build remains unverified. Windows requires a custom encoder build and has no verified build procedure in this release.

### 2. Open MobiPEG Studio

Install Python 3.10 or newer, with Tkinter for the graphical interface:

```sh
python3 native/MobiPEG_Studio_V15.py --gui
```

Choose your input, output mode, quality, resolution per eye, and frame rate, then select **Convert and verify MOFLEX**. Existing output files are preserved by default.

### Command-line usage

Convert a 2D video:

```sh
python3 native/MobiPEG_Studio_V15.py \
  --input "video.mp4" --mode 2d --preset quality
```

Convert a half-side-by-side 3D video:

```sh
python3 native/MobiPEG_Studio_V15.py \
  --input "stereo.mp4" --mode half-sbs --resolution 400x224 --fps 24
```

Use `--mode full-sbs` for full-width side-by-side sources. Add `--max-size-mb 20` to set a 20 MB final output limit. Size-limited conversions can take longer because they try multiple encodes; the job fails if the requested limit cannot be met.

For movies with multiple audio languages, inspect and select a track:

```sh
python3 native/MobiPEG_Studio_V15.py -i "movie.mkv" --list-audio-tracks
python3 native/MobiPEG_Studio_V15.py -i "movie.mkv" --audio-track 1
```

For all options:

```sh
python3 native/MobiPEG_Studio_V15.py --help
```

See the [Studio quick start](native/V15_STUDIO_QUICKSTART.md) for more examples, custom encoder selection, and native test commands.

## Use in a browser

The web version offers the Studio conversion workflow without building a native encoder. It includes scalar and SIMD WebAssembly engines and processes video locally in a worker.

To serve the included app locally, install Node.js 22 or newer and run this from the repository root:

```sh
node scripts/dev-server.mjs
```

Open **http://localhost:4173** in a modern browser. Use the HTTP server rather than opening `index.html` directly. Automatic engine selection uses SIMD when supported; Compatibility selects the scalar engine.

The browser build requires **SharedArrayBuffer and cross-origin isolation**, including when using the scalar engine. The local server supplies the required headers. For phone access or public hosting, use HTTPS; plain HTTP on a LAN does not provide the required secure context.

### Hosting the web version

The repository root contains a ready-to-serve copy of the web app, both WASM engines, and `.nojekyll`. In **Settings → Pages → Build and deployment**, choose **Deploy from a branch**, select **master** and **/ (root)**, then save. No custom build workflow or encoder rebuild is required. The expected address is https://oldhimaster1.github.io/Mobipeg-MOFLEX/.

GitHub still uses its own deployment infrastructure for branch publishing. An account-wide Actions or billing restriction may also block that deployment; branch publishing is not a guaranteed workaround.

The deployable web application is in [`dist/`](dist/). Serve WASM files as `application/wasm` and configure:

```text
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
Cross-Origin-Resource-Policy: same-origin
```

The included `_headers` file works on hosts that support that format. GitHub Pages does not apply that file; the app includes a service-worker isolation fallback whose compatibility depends on the browser. Open the app as a top-level page. The app checks isolation before conversion.

## Compatibility and limitations

This version is a development preview. Native/WASM comparison reports and Chrome conversion tests are included. On November 16, 2026, a user completed browser conversions in iPhone Safari, including a decode-verified five-minute 2D video; one shorter 2D output was confirmed playing on a physical Nintendo 3DS. Long-movie joining, stereo playback, and extended-duration seeking on 3DS hardware remain unverified. Successful software decoding does not by itself establish console compatibility.

For long videos, the browser offers an **experimental Long movie mode**. It encodes chapters of at most 30 seconds separately, stores them on-device using the browser's origin-private file system (OPFS), rebuilds a single MOFLEX with a front seek index, and checks the complete video/audio decode. This avoids keeping the entire encoded movie in WebAssembly memory, but a full-length movie is **not yet tested on a physical 3DS**; seeking beyond 71 minutes is particularly uncertain because the historical seek-table duration field is 32-bit. This mode requires plenty of free local storage, may take hours, and does not support the maximum-size target. Clear the temporary movie copy using the Web Studio button once it has been downloaded. Your source video is never uploaded.

Ordinary browser conversions still buffer each output in memory. The WASM engine's configured 2 GiB limit does not mean that much total tab memory is available. Keep the page open and visible; pause/resume and recovery after closing it are not supported. Browser previews may recognize fewer input formats than the encoder.

Read the [validation report](reports/VALIDATION.md) for test coverage, measured results, and outstanding checks. Additional native experiments and research tools are included under [`native/`](native/); they are separate from the standard Studio workflow.

See the [long-movie preview validation](reports/LONG_MOVIE_VALIDATION.md) for the current memory strategy, audio alignment, duration-field handling, and reproducible checks. Portable native packaging is documented in [native/PORTABLE_BUILDS.md](native/PORTABLE_BUILDS.md).

## Building and development

The complete modified codec sources are in [`native/source/`](native/source/). The browser application is in [`dist/`](dist/), build and packaging tools are in [`scripts/`](scripts/), and regression tools are in [`tests/`](tests/).

To rebuild the browser engines, install Linux build tools, make, pkg-config, Python 3, Node.js, Git, and **Emscripten SDK 4.0.10**. With that SDK installed and activated, set `EMSDK` to its directory and run from the repository root:

```sh
bash scripts/build-wasm.sh
bash scripts/build-simd.sh
node scripts/provenance.mjs
```

Source and engine hashes are recorded in [`dist/engine/provenance.json`](dist/engine/provenance.json).

Run the controller tests with:

```sh
node --test tests/core.test.mjs
```

The native/WASM benchmark requires built engines and your own local video fixtures. Configure `tests/cases.json` for those files before running:

```sh
node tests/benchmark.mjs tests/cases.json
```

Keep personal media and machine-specific fixture paths out of commits. Node-based WASM benchmarks do not replace browser or hardware tests.

## Credits and licenses

Based on [MobiPEG](https://github.com/quatric/mobipeg), its modified [x264 backend](https://github.com/quatric/x264), and [FFmpeg](https://ffmpeg.org/).

The modified FFmpeg and x264 source trees retain their upstream notices and license texts in [`native/source/`](native/source/). Redistribution of binaries must comply with the applicable licenses, including corresponding-source requirements. Web application additions are licensed under GPL-2.0-or-later; see [LICENSE](LICENSE).

MobiPEG is an independent project and is not affiliated with Nintendo or MobiClip.

### Aggregate website statistics

The hosted Web Studio sends a page-view event and, after a conversion passes full
verification, its rounded duration and input/output byte counts to
`https://usage-stats.moflex.workers.dev/ingest`. Media, filenames, conversion
reports and visitor identifiers are not sent. Requests omit credentials and
referrers. The footer provides a persistent browser opt-out; Do Not Track and
Global Privacy Control also disable reporting. Local copies do not report.
Cloudflare processes network metadata to deliver these requests; the separately
managed Worker stores daily aggregate counters. Statistics are best effort,
exclude opted-out or blocked requests, and are not unique-person counts.

Backend administration is separate from this repository. Protect `/panel` and
`/api/stats` with Cloudflare Access while keeping `/ingest` public. The originally
supplied Worker capped input files at 5,000,000,000 bytes; raise its input bound to
support larger sources or their statistics will be rejected. Never rerun a schema
containing `DROP TABLE` against existing counters.

Reporting checks: `node --test tests/usage.test.mjs` (mocked network only).
