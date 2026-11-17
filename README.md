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

The Web Studio also accepts several videos at once. Each queue item keeps its own settings and can be reordered or removed before conversion. Files are encoded one at a time, and the queue deliberately pauses after each completed output until you start its download and continue; this keeps multiple completed movies from accumulating in browser memory. The queue is local to the current tab and is not restored after a reload.

Before encoding, the queue shows a broad output-size range and its estimated peak temporary browser-storage requirement. This is a planning estimate, not a promised file size: motion, detail, audio, and advanced encoder settings can substantially change the result. If the browser exposes storage quota information, MobiPEG also shows the currently available browser storage. Downloaded files use your device's normal download storage and are not included in that quota.

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

### Advanced browser parameters

The optional **Advanced → Parameter overrides** section exposes 16 validated
controls using native parameter names: motion estimation, subpel search, keyframe
interval, skip SAD threshold, motion-vector refinement/penalty/diagonal search,
scaler flags and input range, spatial/temporal hqdn3d coefficients, and audio
gain/highpass/lowpass filters. Empty fields inherit the profile. An invocation
preview displays video/audio argument vectors and codec environment values.
Disabling overrides ignores all their values; Reset clears them. Active values
are saved in the existing local conversion report, never in usage telemetry.

Arbitrary FFmpeg arguments are not accepted. Codec, pixel format, stereo layout,
sample rates, and movie timestamp/frame alignment remain controlled by the
existing conversion pipeline. Known desynchronizing subme 1 is rejected. No
native or WASM binary change is needed for these supported parameters.

Validation: `node --test tests/core.test.mjs tests/movie.test.mjs tests/advanced.test.mjs tests/usage.test.mjs`;
`node tests/advanced-wasm.mjs` generates tiny fixtures and completely decodes
advanced output for both WASM engines and all three video modes;
`playwright test --config tests/browser/advanced.config.mjs` checks mobile form
submission, overrides, validation, cancel and reset with a mocked conversion worker.

### Output preview, framing, and additional presets

The browser's **Output preview** generates a framed source image and a genuine
encoded-and-decoded MobiClip I-frame at the chosen timestamp. Stereo previews
provide separate Left and Right views. It processes one displayed frame, uses the
current profile/quantizer and never counts as a successful conversion. It does
not preview audio, interframe motion behavior, whole-file verification or physical
3DS playback. The final size search can select a different quantizer. Cancel
terminates its worker; settings changes invalidate and release preview buffers.

**Framing & crop** adds Fit, Fill, Stretch, and four even-pixel margins. Margins
apply separately to each SBS eye before SAR correction and scaling. The existing
Fit/default filter path is preserved. Additional per-eye resolution presets span
256×144–800×480. Rates span 10–60 fps, including 23.976, 29.970 and 59.940.
Resolutions above 400×240 and rates above 30 display fps are experimental for
console playback. New options do not change the portable native packages.

Validation: add `tests/framing.test.mjs` to the Node test command;
`node tests/framing-wasm.mjs` covers actual preview pixels and full video/audio
decoding at selected new resolutions/rates and crop modes with both WASM engines;
`playwright test --config tests/browser/framing.config.mjs` covers real browser
preview, stereo eye colors, crop, cancel, verified conversion and mobile layout.

### Speed, crop ratios, and interface languages

**Encoding speed → Fast** reduces `MOBI_SUBME` to 2 while retaining the profile's
quantizer, motion-estimation method, and refinement setting. Explicit Advanced
subme overrides take precedence. Original remains the default. Fast changes
compressed pixels and size; it is an optional quality/speed tradeoff, not a
bit-exact acceleration. Full decoding checks remain active. Long-movie chapters
reuse validated metadata from the initial inspection, eliminating one redundant
probe/module startup per chapter without changing encode arguments.

**Letterbox / Fit** now has an explicit name. Crop aspect ratio offers 4:3, 16:9,
16:10, 5:3, 21:9, 1:1, and 9:16. Crops are centered on even pixels after manual
margins, account for SAR, and apply to each SBS eye independently. Framing then
fits, fills or stretches into the selected output resolution.

The header offers eight local interface languages: English, Spanish, French,
German, Portuguese, Japanese, Korean and Simplified Chinese. No translation API,
account, video upload, or locale telemetry is used. Browser language is selected
initially; a localStorage preference remembers subsequent choices. Technical
logs, source filenames, track metadata, and the English guide remain unchanged.
A MutationObserver translates changed interface nodes rather than rescanning the
whole document on every progress tick; raw parameter values are preserved.

Additional regression checks: `node --test tests/options.test.mjs`;
`tests/browser/options.spec.mjs` (included in the framing config) checks all eight
languages and 390/768/1024/1280 px layouts, local persistence, settings, filenames,
and privacy preferences. The framing WASM checks now exercise Fast and per-eye
aspect crops. The 65-second scalar/SIMD browser movie tests exercise cached
metadata, Fast, three OPFS chapters, Japanese audio selection, complete decoding,
and cleanup. They remain synthetic tests, not physical 3DS or iPhone evidence.

Reproduce the stage-time benchmark with
`node tests/speed-benchmark.mjs reports/speed-validation-20261117.json`.
The report records three repetitions, frame/decode checks and source-reference
PSNR for each mode and engine. It excludes source generation, WASM module loading,
audio and final verification, and measures a short generated chart rather than a
full movie. Run it without other benchmarks for interpretable timings.
