> Read **HANDOFF.md first** for the completed final half-SBS tests and remaining browser/hardware limits. Nothing has been published.

# MobiPEG Web Studio — V15 layout-0 port

This project compiles the user's actual patched FFmpeg/x264 MobiClip encoder to WebAssembly. It is not H.264 conversion renamed to MOFLEX. `native/` contains the supplied fixed V15 package, including its source and licenses. `dist/engine/provenance.json` records hashes of the codec, muxer, corrected demuxer and compiled WASM.

## Run the included website

Install Node.js 22 or newer. In this folder:

```
node scripts/dev-server.mjs
```

Open http://localhost:4173 in a modern browser. Do not open index.html using file://. The local HTTP server only serves application assets; it does not receive media. All conversion occurs in the browser worker. To test a phone, serve the site over HTTPS from a host with COOP/COEP headers; plain HTTP on a LAN is not a secure context.

The initial engine download can be large. Keep the page visible and the screen awake. Physical iPhone Safari and Nintendo hardware are separate validation targets; see `reports/VALIDATION.md` for the actual coverage.

## Rebuild the real encoder

Prerequisites: Linux build tools, make, pkg-config, Python 3, Node.js, Git, and Emscripten SDK 4.0.10. Obtain emsdk from the official emscripten-core/emsdk repository, then:

```
./emsdk install 4.0.10
./emsdk activate 4.0.10
export EMSDK=/absolute/path/to/emsdk
bash scripts/build-wasm.sh
bash scripts/build-simd.sh
```

The script builds the supplied modified x264 first, then the supplied FFmpeg, links x264 into the WASM core, and creates the source provenance file. The second script builds an optional SIMD codec variant; run `node scripts/provenance.mjs` afterward to hash both. It does not use a stock ffmpeg.wasm core. Automatic mode selects the SIMD codec when supported; Compatibility selects the scalar build. Both preserve the same MobiClip syntax. The codec is configured for one encode thread; FFmpeg 8's scheduler still needs pthreads and SharedArrayBuffer. Its worker pool is created before calling main. Each command uses a fresh instance because the original FFmpeg CLI and V15 motion refinement contain process-global state.

Rebuild native for comparison:

```
bash native/BUILD_FOR_LINUX.sh
```

The original project includes macOS instructions in native/. Windows compilation has not been verified here.

## Tests

```
node --test tests/core.test.mjs
node tests/benchmark.mjs tests/cases.json
```

`tests/core.test.mjs` checks settings, all supported filter combinations against Python V15, quantizer mapping, motion settings, candidate-size enforcement, stereo pairing, and failed-verification rejection. Some controller error-path tests use deliberately controlled fake engine responses; these are not presented as real encodes.

`tests/benchmark.mjs` uses the *real* built native and WASM cores, applies the shared conversion workflow, verifies full decode, saves actual files, and compares native/WASM results. It requires private source videos supplied by the user. Edit fixture paths in tests/cases.json for your machine. Original source videos are intentionally not distributed with the website. The benchmark executes browser WASM under Node; this is not equivalent to a Safari or Firefox run.

## Application structure

- `dist/core.mjs`: port of V15 Studio settings, filters, quantizers, stereo timing, candidate search, audio and verification.
- `dist/worker.js`: native WASM loader and command adapter. Files are mounted read-only with WORKERFS rather than copying the original input into the WASM filesystem.
- `dist/app.mjs`: local previews, drag/drop, configuration, progress, stage ETA, cancellation, downloads, reports and optional wake lock.
- `scripts/build-wasm.sh`: reproducible custom native-source build.
- `tests/`: controller parity and real encode regression tools.
- `native/`: complete original fixed V15 package and offline research scripts.

## Stereo correctness

2D uses layout 6. Full-/half-SBS are cropped into isolated eyes, filtered/scaled separately, then temporally interleaved LEFT,RIGHT. Stereo's coded rate is twice the displayed rate, including rational rates. Both encode and audio remux pass `-mo_layout 0 -mo_interleave_input_double_rate 1`. The corrected bundled demuxer exposes doubled coded FPS, so the browser does not apply legacy timestamp compensation. Audio length is computed from actual coded frames divided by coded FPS. Odd stereo frame counts and remux/verification frame mismatches fail the job.

## Limits and honest release status

This is a functional release preview, not a certification that arbitrary movies work on all devices. It preserves the normal Studio pipeline, not every sample-specific offline optimization/research script as a browser UI. Those scripts remain included in native/.

The normal supplied MOFLEX muxer buffers packets and its media payload in memory to produce the front seek table. WORKERFS avoids copying large original inputs but does not remove those internal buffers, decoder buffers, final output copies or per-command heaps. Large/long conversions can fail. This version does not implement a disk-backed muxer or crash recovery. The current WASM linear-memory limit is 2 GiB, while practical mobile limits may be much lower; process memory also includes workers, blobs and JS data. Reported WASM heap is not total tab memory.

Size caps may require up to nine encodes. V15's quantizer search assumes broadly monotonic output size; it chooses the lowest *tested* feasible quantizer, not a mathematical proof of the globally best quantizer when codec/container size behaves non-monotonically. Source-native V15 uses the same search strategy.

ETA is for the current stage. Cancellation terminates the worker and its execution; no pause/resume exists. Browser preview codecs can differ from FFmpeg's accepted formats. No subtitles, depth generation, new streaming backend, or remote video retrieval is added. FFmpeg network protocols are disabled in the browser build.

## Hosting

Serve dist/ over HTTPS, with application/wasm for WASM files and:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
Cross-Origin-Resource-Policy: same-origin
```

The package includes `_headers` for hosts supporting that format. On static hosts that ignore `_headers`, `isolation-sw.js` attempts same-origin header injection and reloads once; browser support must be tested and the app reports missing isolation instead of faking conversion. The included Node server sends headers directly. Open the site as a top-level page; an embedded preview may not support isolation. No third-party fonts, analytics, APIs or media uploads are used.

## Licenses

The supplied modified x264 and GPL-enabled FFmpeg retain their respective source notices and license texts in native/source/. Distribute corresponding modified source with the binary under the applicable GPL terms. Web application additions are GPL-2.0-or-later; see LICENSE. This independent project is not affiliated with Nintendo or MobiClip.
