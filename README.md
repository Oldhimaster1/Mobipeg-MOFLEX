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

The [Pages deployment workflow](.github/workflows/pages.yml) publishes only the web assets and license, after checking controller tests and recorded source/engine hashes. To enable it, open **Settings → Pages → Build and deployment → Source → GitHub Actions**. Then run **Deploy web app to GitHub Pages** from the Actions tab. Subsequent app changes on master deploy automatically. The expected address is https://oldhimaster1.github.io/Mobipeg-MOFLEX/.

The deployable web application is in [`dist/`](dist/). Serve WASM files as `application/wasm` and configure:

```text
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
Cross-Origin-Resource-Policy: same-origin
```

The included `_headers` file works on hosts that support that format. GitHub Pages does not apply that file; the app includes a service-worker isolation fallback whose compatibility depends on the browser. Open the app as a top-level page. The app checks isolation before conversion.

## Compatibility and limitations

This version is a development preview. The included reports document Linux native tests, native/WASM comparisons, and Chrome conversion tests. Physical iPhone Safari, Firefox/WebKit, and Old/New Nintendo 3DS playback remain unverified for this version. Successful software decoding alone does not establish console compatibility.

Long or complex videos may exceed available memory, especially on mobile devices. The browser's muxer buffers output in memory, and its 2 GiB WASM linear-memory limit is not a measure of total tab memory. Keep the page visible during conversion; pause/resume and recovery after closing the tab are not supported. Browser previews may support fewer input formats than the encoder.

Read the [validation report](reports/VALIDATION.md) for test coverage, measured results, and outstanding checks. Additional native experiments and research tools are included under [`native/`](native/); they are separate from the standard Studio workflow.

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
