# MobiPEG

Convert videos to MobiClip video in `.moflex` containers for Nintendo 3DS playback. MobiPEG includes a desktop interface, command-line tools, and an optional browser app, built around modified FFmpeg and x264 sources.

## Features

- **2D and stereoscopic 3D:** convert ordinary videos or full- and half-side-by-side stereo sources.
- **Quality and size controls:** choose a quality preset, image cleanup filter, motion refinement, and an optional maximum output size.
- **3DS-sized output:** select 400×240, 400×224, or 320×240 per eye, with integer and fractional frame rates.
- **Audio conversion and verification:** convert audio to compatible ADPCM or optional FastAudio and check the completed output by decoding it.
- **Local processing:** use the native tools on your computer or convert in a browser without uploading your video.
- **Parallel movie conversion:** split a movie timeline into independent aligned ranges (the input does **not** need chapters), show per-worker progress, and join the MOFLEX seek index in playback order. Choose between 1 and your device's advertised logical CPU count.
- **MOFLEX playback and export:** open a local `.moflex`, seek, select stereo eyes, play ADPCM or FastAudio, and export MP4/MKV without uploading it.

- **Indexed movie seeking:** eligible MobiPEG movies now seek through validated sync/keyframe entries in native and scalar/SIMD browser decoders, with safe forward decoding for unsupported files. Generated 30–120-minute tests verify exact video and audio against reference decoding.
- **Scene-aware size targeting:** multi-range movie jobs sample source texture and motion, allocate more video budget to difficult ranges, and reuse unused bytes as queued ranges start. Choose Scene-aware or Uniform in the browser; native parallel jobs accept `--budget-mode scene|uniform`. Equal-actual-size testing currently ties manually retuned uniform allocation; no general coding-efficiency gain is claimed. See [measurements and limitations](reports/INDEXED_SEEK_COMPRESSION.md).

3D conversion requires a source with separate left and right views; it does not generate depth from a 2D video.

Validated MobiPEG-indexed movies now support fast native and browser seeking, with conservative forward decoding for unsupported files. Generated 30–120-minute fixtures were checked against reference video and audio. Size-targeted multi-range movies can use **Scene-aware** texture/motion allocation or the previous **Uniform** allocation; native parallel jobs expose `--budget-mode scene|uniform`. The measured benefit is better use of the requested size budget; equal-actual-byte quality matched the manually retuned baseline. See [measurements and limitations](reports/INDEXED_SEEK_COMPRESSION.md).

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

For desktop movie encoding, the **Parallel encoders** slider (or `--workers N`) starts independent custom FFmpeg processes for aligned video ranges, without looking for source chapters. One worker retains the original single-pass encoder path. Multiple workers are an experimental movie path: final video and audio are fully decoded for verification, but long-film playback on a physical 3DS remains unverified. More workers require proportionally more memory and temporary disk space.

The Web Studio also accepts several videos at once. Each queue item keeps its own settings and can be reordered or removed before conversion. Files are encoded one at a time, and the queue deliberately pauses after each completed output until you start its download and continue; this keeps multiple completed movies from accumulating in browser memory. The queue is local to the current tab and is not restored after a reload.

Before encoding, the queue shows a broad output-size range and its estimated peak temporary browser-storage requirement. This is a planning estimate, not a promised file size: motion, detail, audio, and advanced encoder settings can substantially change the result. If the browser exposes storage quota information, MobiPEG also shows the currently available browser storage. Downloaded files use your device's normal download storage and are not included in that quota.

The estimate also displays an approximate peak RAM budget for concurrent browser encoders. It is intentionally conservative and cannot predict how much memory Safari or another browser will actually allow. On phones and tablets, keep the worker slider at **1** unless you have tested higher settings on your device.

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

Use several CPU cores to encode a long 2D movie without source chapter markers:

```sh
python3 native/MobiPEG_Studio_V15.py \
  --input "movie.mp4" --mode 2d --workers 4
```

Use `--mode full-sbs` for full-width side-by-side sources. Add `--max-size-mb 20` to set a 20 MB final output limit. Size-limited conversions can take longer because they try multiple encodes; the job fails if the requested limit cannot be met.

For movies with multiple audio languages, inspect and select a track:

```sh
python3 native/MobiPEG_Studio_V15.py -i "movie.mkv" --list-audio-tracks
python3 native/MobiPEG_Studio_V15.py -i "movie.mkv" --audio-track 1
```

Use **Audio offset (ms)** in either Studio interface to correct sync. A positive
value delays audio and a negative value starts it earlier. The desktop CLI
equivalent is `--audio-offset-ms 250` for a quarter-second delay. The shift is
applied on the movie timeline, including across parallel ranges. The output
keeps the original video duration and fills uncovered parts with silence.

Enable **Normalize audio peak** or pass `--normalize-audio` to scan the selected
track and apply one gain to the entire movie. It aims for a PCM peak of −1 dBFS
before compression, with up to 24 dB of amplification. This setting adds an
audio analysis pass. It adjusts peak level rather than perceived loudness.

Desktop Studio's **HDR to SDR** setting converts tagged PQ and HLG to BT.709
SDR. Automatic mode uses Mobius tone mapping. Use `--hdr-mode` in the CLI to
select a different operator or disable tone mapping. Browser HDR conversion
is still under development.

For all options:

```sh
python3 native/MobiPEG_Studio_V15.py --help
```

Choose `--audio-codec fastaudio` for the smaller experimental audio format. The
Studio checks that the selected build contains the encoder and falls back to
ADPCM when it is unavailable or fails. FastAudio is fully software-decode tested,
but its playback on a physical Nintendo 3DS has not been verified; ADPCM remains
the default compatibility choice.

Inspect or convert an existing MOFLEX with the bundled decoder:

```sh
python3 native/moflex_convert.py movie.moflex --inspect
python3 native/moflex_convert.py movie.moflex -o movie.mp4 --mode sbs
python3 native/moflex_convert.py movie.moflex -o left-eye.mkv --mode left
```

`--mode auto` exports stereo files as SBS and 2D files as 2D. Other choices are
`2d`, `sbs`, `left`, and `right`. Layouts 0–1 (alternating eyes), 2–3
(top/bottom), 4–5 (side-by-side), and 6 (2D) are read from the MOFLEX descriptor.
The inspector samples decoded pixels to label two-eye material as genuine 3D or
duplicated eyes. That label is a heuristic: nearly static or extremely subtle 3D
can be misclassified. MP4/MKV exports are completely decoded before success is
reported and preserve the first audio stream as AAC.

See the [Studio quick start](native/V15_STUDIO_QUICKSTART.md) for more examples, custom encoder selection, and native test commands.

## Use in a browser

The web version offers the Studio conversion workflow without building a native encoder. It includes scalar and SIMD WebAssembly engines and processes video locally in a worker.

To serve the included app locally, install Node.js 22 or newer and run this from the repository root:

```sh
node scripts/dev-server.mjs
```

Open **http://localhost:4173** in a modern browser. Use the HTTP server rather than opening `index.html` directly. Automatic engine selection uses SIMD when supported; Compatibility selects the scalar engine.

Open **http://localhost:4173/player.html** for the separate **MOFLEX Player**. Pick a local `.moflex` file to display video with the actual MobiClip decoder; ADPCM and FastAudio are decoded to short PCM buffers and played through WebAudio when available. Descriptor layouts 0–6 support 2D, alternating-eye, top/bottom, and side-by-side material. The player can export 2D, SBS, left-eye, or right-eye video to MP4/MKV. Browser export currently uses standard MPEG-4 video plus AAC and buffers the completed output in WASM memory, so use the desktop converter for large movies. The player itself only keeps short decoded frame batches in RAM, so a long movie does not have to be expanded into full uncompressed video. Seeking, playback rate and audio synchronization depend on browser performance and should be tested on the target device.

The player includes a **SUPER MOFLEX** editor for metadata, poster art,
subtitle files, and one alternate audio track. Save an edited copy without
re-encoding the original movie, or choose the embedded tracks during playback.
SRT, ASS, and SSA show as plain text in the browser. MKV can carry embedded
subtitles from the browser; desktop export can also put text subtitles in MP4.
Nintendo's original player uses the primary movie streams. Trailer-aware
software can read the appended extras.

Desktop examples:

```sh
python3 native/super_moflex.py input.moflex
python3 native/super_moflex.py input.moflex -o edited.moflex \
  --metadata movie.json --subtitle ENG captions.srt --alternate-audio JPN dub.wav
python3 native/moflex_convert.py edited.moflex -o export.mkv --audio all --subtitles all
```

To package one or more existing movies on desktop, provide a local
VidInjector9002-CLI build. MobiPEG creates the ordered project, packages the
movie streams, and verifies the CIA title ID, content hashes, and exact size.
Choose an unused title ID from C0000 through EFFFF. If you maintain a list of
installed IDs, put them in `reserved_title_ids` in the project JSON.

```sh
python3 native/cia_builder.py new series.json episode1.moflex episode2.moflex \
  --title 'My series' --id C1234
python3 native/cia_builder.py build series.json series.cia --backend /path/to/VidInjector9002-CLI
```

The JSON project controls each episode's menu title and optional banner, plus
the application title, publisher, icon, and banner. Run `preview` instead of
`build` with a PNG output and `--asset icon` or `--asset banner` for the
backend's preview. A prepared banner binary can supply its own banner audio.
MobiPEG does not bundle the external tool or its player assets. The experimental browser CIA builder can fetch those files from VidInjector when explicitly enabled; see the licensing and verification caveat below.
Physical installation testing is pending.

Choose **Save app for offline use** in the footer to cache the converter, player,
and both WASM engines. After the status confirms setup, you can reopen and use
them offline. On iPhone and iPad, Safari offers **Share → Add to Home Screen**.
While batch encoding, **Save in this browser** stores verified outputs locally
and starts the next item automatically. A browser that offers a folder picker
can save directly to a selected folder. Browser-saved outputs remain available
after reload. Batch queue order and per-video settings are also saved locally;
reselect the original files after reopening the app to continue unfinished items.
This restores the queue, not the source video bytes.
If an old or damaged queue cannot be read, MobiPEG leaves its saved data alone
and asks before discarding it.

The browser build requires **SharedArrayBuffer and cross-origin isolation**, including when using the scalar engine. The local server supplies the required headers. For phone access or public hosting, use HTTPS; plain HTTP on a LAN does not provide the required secure context.

### Browser HDR to SDR conversion

Web Studio now offers an HDR-to-SDR selector with **Auto**, **Off**, **Mobius**,
**Hable**, and **Reinhard** tone mapping and optional manual **PQ/HDR10** or
**HLG** source override. Tagged HDR is detected from the video stream.
Conversion takes place inside the existing WASM worker via a dynamically
generated BT.2020-to-BT.709 3D LUT. SDR input is left untouched. The LUT
implements a 100-nit SDR reference and a 1000-nit HDR roll-off; it is not a
reference-grade mastered color transform. For critical color work, compare
against a display-referred reference. An HDR output may have different
brightness/chroma depending on the mastering display.

No other video services, paid APIs, or server processing are involved.
The bundled WASM engine's `lut3d` filter decoded a generated PQ and HLG
sample successfully, and each could be encoded to a MOFLEX file and decoded
in a second WASM process in local synthetic checks. The committed
`tests/hdr-wasm.test.mjs` exercises these paths in a full checkout.
Device-specific Safari behavior, real movies, and physical 3DS playback
are still unverified.

### CIA building in the browser

Open the CIA builder and select your MOFLEX movies. You can supply a compatible,
decrypted player CIA yourself, or explicitly enable **Get the VidInjector player automatically**.
The latter fetches three upstream resources from a pinned VidInjector GitHub revision
and assembles a starter locally. MobiPEG does not include those third-party binary
files in this repository. This is **experimental**: VidInjector's player binary
redistribution rights have not been established, and the automatically generated
CIA has **not** passed a physical 3DS installation/playback test. The pinned
automatic-player path has passed installation, menu, two-episode video/audio
playback, menu return and relaunch checks in Azahar 2126.2. Do not use or
redistribute the upstream files without the necessary permissions.

After selecting an allowed player source, **Build CIA** rebuilds the movies,
metadata and menu, and recalculates RomFS, NCCH, TMD, ticket and content hashes.
An internet connection is required when obtaining the VidInjector resources
unless you already have your own local player CIA.

A compatible collection template can now be reused for 1–27 episodes. The browser
rebuilds directory/file metadata and hash buckets, episode-count settings, ordered
titles and thumbnail lists. A single-movie template still supports one movie,
because it carries a different player/menu configuration. Use a collection-player
template to build seasons. Tests reuse a two-episode native template for 1, 2, 5,
10, 20 and 27 episodes and verify payloads, title rows, settings, executable and
menu resource preservation through independent extraction.

HOME Menu icons and episode thumbnails accept PNG, BMP and JPG images, plus
prepared SMDH/BIMG files. Images are center-cropped and resized to tiled RGB565.
HOME Menu banner images can replace a compatible 256×128 RGB565 texture inside
the selected template's CGFX model. Animation and model resources are retained.
Unsupported models give an explicit error and can use prepared CBMD banners.
Optional mono/stereo PCM16 WAV audio at 8–48 kHz and up to ten seconds is packed
into CWAV. Leaving audio blank retains the template's audio. Independent
vgmstream decoding preserved every original mono/stereo PCM sample. Physical
console banner display and audio remain unverified.

Prepare synthetic console-test movies with
`python3 scripts/prepare-cia-device-test.py /path/to/new-test-directory`.
Follow [the device checklist](reports/CIA_DEVICE_TEST.md) with your own legally
obtained local collection template. The kit distributes no player executable.

SHA-256 content hashing reads 1 MiB chunks. RomFS integrity hashing uses 4 KiB
blocks, and movie data remains in Blob slices. Executable/ExeFS prefix allocation
is limited to 16 MiB. Output is assembled as a Blob and checked against FAT32.
Enable splitting to partition an oversized collection in order, using consecutive
title IDs. The splitter conservatively reserves the template size plus 64 MiB per
part for packaging overhead. Every finished CIA receives a final FAT32 check.
Enable **Save completed CIAs in this browser before downloading** to stream each
finished output into OPFS and retain it for download/delete after reload.
Actual multi-gigabyte builds, mobile peak memory and Safari are unverified.
The browser validates source and final content hashes, NCCH section hashes and
matching IDs. Independent native verification and extraction passed for generated
single- and two-movie outputs, including exact movie bytes. Structural checks
cannot establish physical 3DS installation or playback, which remain untested.

The JSON export and native builder remain available. To run the native-reference
integration test, set `MOBIPEG_CIA_BACKEND` to your VidInjector9002-CLI executable
and run `node --test tests/cia-packager.test.mjs`. The Chromium test takes
`MOBIPEG_TEST_CIA_TEMPLATE` and a JSON array of local movie paths in
`MOBIPEG_TEST_CIA_MOVIES`, using `tests/browser/upgrade.config.mjs`.

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

### Check MOFLEX files before copying them to a 3DS

The native **MOFLEX preflight** tool checks the seek-index structure, video layout,
frame rate, per-eye dimensions, FAT32 size limit, and appended SUPER MOFLEX tracks.
It warns about experimental resolutions and frame rates and the known seeking
uncertainty after approximately 71 minutes. It reads the file without changing it.

```sh
python3 native/moflex_check.py movie.moflex
python3 native/moflex_check.py movie.moflex --json
```

A passing structural check **does not** mean every MobiClip frame decodes or
that the video has been tested on a physical Nintendo 3DS. For stronger
assurance, also run a full decode using the project's patched FFmpeg and test
the movie on the console and player you intend to use. The tool does not
require FFmpeg for the initial structural check.

## Compatibility and limitations

This version is a development preview. Native/WASM comparison reports and Chrome conversion tests are included. On November 16, 2026, a user completed browser conversions in iPhone Safari, including a decode-verified five-minute 2D video; one shorter 2D ADPCM output was confirmed playing on a physical Nintendo 3DS. FastAudio, MOFLEX-to-video export, layouts 1–5, long-movie joining, stereo playback, and extended-duration seeking have software tests but remain unverified on 3DS hardware. No retail/proprietary MOFLEX sample is committed or claimed as tested; automated coverage generates files with this repository's muxer. Successful software decoding does not by itself establish console compatibility.

For long videos, the browser offers an **experimental Long movie mode**. It encodes independent timeline ranges of at most 30 seconds, stores them on-device using the browser's origin-private file system (OPFS), rebuilds a single MOFLEX with a front seek index, and checks the complete video/audio decode. No source chapter information is required. With two or more workers, each worker takes the next available range, with separate progress indicators. This avoids keeping the entire encoded movie in WebAssembly memory, but concurrent WASM encoders can still exceed browser memory limits, particularly on mobile. A full-length movie is **not yet tested on a physical 3DS**; seeking beyond 71 minutes is particularly uncertain because the historical seek-table duration field is 32-bit. This mode requires plenty of free local storage, and may take hours. Clear the temporary movie copy using the Web Studio button once it has been downloaded. Your source video is never uploaded.

**Maximum size** works with Long Movie Mode and parallel conversion in the browser
and on desktop. It divides the limit by coded frame count and measures each
complete range with audio and an index. Ranges that fit at the selected
quantizer are kept. Others retry with stronger compression. The exact joined
size is checked before writing the final file. A complex range may run out of its
share while simpler ranges have room left. In that case, raise the size limit,
lower the resolution or frame rate, or split the movie.

Long Movie Mode and parallel browser conversions can save verified ranges when OPFS and Web Locks are available. To continue after pausing, reloading, or reopening the site, select the same original file with the same settings and start the conversion again. MobiPEG checks the source contents and verifies the integrity of stored ranges before reuse. A range interrupted before it can be saved is encoded again. Browser storage eviction can remove checkpoints. The **Saved movie recoveries** panel shows unfinished jobs. Damaged checkpoints are marked clearly and can be deleted with confirmation; they are not treated as resumable. Downloaded files saved outside the browser remain yours, and outputs saved in private browser storage can be downloaded again until that storage is cleared or evicted.

Desktop CLI users can add `--resume` to a parallel conversion (`--workers 2` or more). Run the same command to continue. Checkpoints are stored in a `.mobipeg-checkpoints` directory next to the destination. After abandoning a job, its checkpoint folder can be removed once all Studio processes using it have closed.

Ordinary browser conversions still buffer each output in memory. A tab can run out of memory before the WASM engine reaches its configured 2 GiB limit. Keep the app visible while encoding. Browser previews may recognize fewer input formats than the encoder.

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

The browser's **Output preview** compares the framed source with genuine decoded
MobiClip at the chosen timestamp. Choose a still image or enable **Motion preview**
for up to 2.5 seconds of silent footage. Both views share a playhead and offer
left- and right-eye selection for stereo sources. Motion previews encode at the
selected settings, then downsample the display to limit memory use. The final
size search can select a different quantizer. Cancel terminates the preview
worker, and settings changes release the preview buffers.

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

### Azahar-tested CIA milestone

Browser-built 400×240 ADPCM collections passed actual Azahar 2126.2 menu and playback checks at 2, 5, 10, 20 and 27 episodes, including first/middle/last selections. Two-episode seeking, normal exit/relaunch and stereo eye presentation were checked. Physical 3DS compatibility remains unverified. See [the runtime validation report](reports/AZAHAR_VALIDATION.md) for evidence, exact scope and remaining limitations. New interleaved stereo encodes use layout 1 for left-first frames, matching the tested player. Previously generated layout-0 stereo files may need re-encoding for correct eye order in this player.

### Reopening CIA projects and using saved conversions

In the CIA builder, select a saved project JSON and its original movies and artwork,
then choose **Open project**. Episode order, titles, artwork and splitting settings
are restored after the media passes inspection. Keep the JSON with the original
files; it contains settings and filenames, not videos. Select your local player
template separately when building.

**Add conversions saved in this browser** opens batch outputs already stored by
MobiPEG on the same browser and website. This avoids downloading and reselecting
those movies. Browser storage can be cleared or evicted, so retain your own copies.
If saving a finished CIA fails, MobiPEG still offers the completed CIA for download.

CIA content hashing uses a small, fixed-memory WASM core with a JavaScript
fallback. Both read files in chunks of at most 1 MiB. The optional stress tools
are `scripts/stress-cia-hash.mjs`, `scripts/stress-long-movie.py`, and
`tests/browser/stress.config.mjs`; see the progress report for measured results
and their scope. Private browsing may provide too little storage to retain a
large CIA, even when the finished download itself is valid.

The browser reliability milestone independently verified generated 5-, 10-, 30-,
60-, 90- and 120-minute MOFLEX files, including every decoded audio sample against
the original clip sequence. Chromium also built, split, downloaded and reopened
a 4.31 GB collection from browser storage. These are synthetic software tests;
physical iPhone and 3DS long-movie behavior remains unverified. The safe forward
decoder can still make long seeks slow. Detailed scope and benchmarks are in
[the progress report](reports/UPGRADE_PROGRESS.md).

### Indexed seeking and scene-aware size targets

The player now uses guarded indexed access for supported MobiPEG files, selecting
real intra starts and preserving audio clocks and stereo eye pairs. Generated
30–120 minute movies seek in seconds in the tested browsers. Unknown files or
stereo streams without suitable intra starts retain the safe forward fallback.

Multi-range browser jobs and native parallel jobs with a maximum size now measure
source texture and motion activity, weight video budgets, and redistribute unused
bytes to queued ranges. Fixed audio and in-flight work remain reserved. The
original short-video path is preserved. Testing showed better use of the requested
cap; matched-actual-size quality tied a manually retuned uniform baseline.
See [measurements and limitations](reports/INDEXED_SEEK_COMPRESSION.md).
