# MobiPEG upgrade progress

Roadmap baseline: `1e46f0db1a` on `master`. This revision already contains desktop and browser MOFLEX export, descriptor-based stereo playback, and optional FastAudio.

## Stage 1

- Browser Studio and desktop Studio enforce the 4,294,967,295-byte limit on completed MOFLEX files. Browser queue estimates show per-file headroom and warn before encoding if the estimated upper bound crosses the limit. Desktop reports equivalent headroom in its conversion log. Estimates remain content-dependent.
- Browser and desktop assembly check media continuity counters, validate indexed sync blocks and descriptor consistency, and detect valid sync blocks omitted from the index. Browser assembly also rejects sparse segment lists.
- Relevant files: `queue.mjs`, `app.mjs`, `movie.mjs`, their deployment copies, `native/moflex_join.py`, and `native/MobiPEG_Studio_V15.py`.
- Regression commands: `node --test tests/*.test.mjs` and `MOBIPEG_ENGINE_DIR=dist/engine-simd node --test tests/player-wasm.test.mjs`. Test vectors use generated media. This milestone changes no codec binaries or compression settings.
- Foundation commit `4df735c7b1`: 304 tests passed, including native and WASM export, a two-worker WASM join, and structural fault injection. FAT32 is exercised at the numeric boundary without allocating a 4 GiB fixture.

The supported browser and Studio paths use the modified FFmpeg muxer and x264 MobiClip encoder. The browser mounts input with WORKERFS, emits independent OPFS ranges, and verifies the assembled file with separate video and audio workers. The native Studio uses independent FFmpeg processes for ranges, then streams the join through a temporary file. The legacy native research scripts have separate entry points. The browser player uses bounded decoded batches. Existing queue settings and output are tab-scoped. The isolation service worker currently serves the Pages isolation requirement.

Browser checkpoints use `checkpoints.mjs` and OPFS with a versioned manifest and independently committed range records. Full source hashing reads 8 MiB at a time. Each saved range is decode-verified and checksummed. Selecting the same original and settings resumes after reload or a worker failure. OPFS eviction can remove saved data. A tab that finishes a job still owns that download. Stored queues and saved-job browsing remain future work.

Desktop CLI `--resume --workers N` stores checksummed, decode-verified ranges next to the output and checks the source and encoder binary before resuming. Run `python3 tests/test_native_resume.py` for a real two-worker assembly interruption with a corrupted range. It passed and reused the intact range only. The Chromium OPFS test passed with a missing range, a same-size corrupt range, changed source contents, and a competing lock.

Chromium SIMD encoded a generated 65-second half-SBS fixture on two workers in 46.4 seconds from conversion start through full decode verification. It produced 43,323,392 bytes, 3,120 coded frames, and four ranges, preserved the selected Japanese-labeled test tone, and released temporary files after download. This is one test-host observation, with no before-and-after speed comparison.

The Chromium scalar run reloaded after saving range one, selected the same source and settings, reused that range, and finished with 3,120 coded frames and 43,339,776 bytes. The resumed attempt took 50.3 seconds from restart to verification. Both browser runs decoded the selected audio track and checked the downloaded file.

Recovery commit: `d843dfd2d8`. Remaining Stage 1 work includes packet-level and A/V boundary validation, a saved-job browser and storage management controls, and estimates for future container features.

## Stage 2

- The browser's bounded worker pool and desktop Studio now take the next range as soon as a worker is free. Range boundaries, bitstream settings, and ordered assembly stay the same. Browser movie progress is weighted by coded frames and accounts for restored ranges.
- Desktop FastAudio capability checks now confirm the actual encoder and muxer option. FFmpeg's help command can return success for an unknown encoder. Single-file browser conversion reuses inspected metadata to warn about potential oversize when the browser's built-in player cannot determine source duration.
- The uneven-work test confirms that an idle worker continues while range one is still running. The real two-worker scalar WASM regression generated, joined, and fully decoded 975 frames and 3,473,408 bytes in 12.5 seconds on the test host. The native interruption/corruption test still passes. The host exposes five logical CPUs with a four-CPU quota. Eight workers are covered by schedule tests, with physical throughput testing pending.
- The full Node suite passed 306 tests. Four recent Chromium UI tests passed, including serial conversion, export, and full decode of two short videos.
- Scheduling and inspection commit: `16fa8b42ab`.
- Motion preview is available alongside the still preview in Web Studio. It uses the selected MobiClip settings for up to 2.5 seconds, then downsamples both display streams to at most 256 × 156 and 12 frames/s per eye. The two retained RGBA streams together use at most about 19 MB. Playback and scrubbing share a frame clock. Chromium validated changing pixels, stereo pairing, eye selection, playback, and invalidation on both scalar and SIMD builds.
- Chromium framing suite: 10 passed in 40.3 seconds, including both motion previews, both existing still-preview and conversion workflows, language preferences, and the queue workflow. The two motion tests took 4.1 seconds (scalar) and 3.9 seconds (SIMD), including UI and fixture interactions.
- Motion preview commit: `277b74cc83`.
- Browser and desktop final verification compare decoded audio duration with video to within one 256-sample codec block plus rounding at 48 kHz. The native checkpoint test now verifies a short pulse on both sides of a real parallel join. Browser results report the actual FastAudio or ADPCM codec, including compatibility fallback on single-file conversions.
- Final audio milestone checks: 307 Node tests passed, the native recovery and pulse test passed, and the two-worker Chromium SIMD fixture passed the stricter check. Its 65-second output added 128 terminal samples and had the same 43,323,392-byte size as the earlier SIMD run. The full conversion took 36.9 seconds in this run. This measurement is not a controlled speed comparison.
- Whole-movie size limits now work in browser Long Movie Mode and in browser and desktop parallel conversion. Each range gets a coded-frame-weighted budget in 4,096-byte blocks, including its audio and seek index. An actual muxed output is measured at each trial. A fitting preset range is encoded once. The join checks its exact size before opening the destination. The allocation is conservative and currently does not move spare bytes from simple ranges to complex ones.
- The 850,000-byte real moving fixture produced 823,296 bytes in Chromium with one worker, 831,488 bytes with two, and 827,392 bytes in native Studio with two. All three outputs retained 216 coded frames and decoded audio. Both browser tests and both native tests passed. The Node suite passed 310 tests, including rejection one byte below the exact joined size without opening the output.
- Size target commit: `7134b895ef`. Both Studio interfaces now offer signed audio offsets of up to 30 seconds. Desktop also exposes `--audio-offset-ms`. The shift follows the complete timeline across ranges and pads uncovered audio. Native tests verified -40 ms and +40 ms around a real join and full silence at offsets of ±9,000 ms on a nine-second fixture. Chromium verified the 250 ms leading silence, final size, frame count, and audio decode with one and two ranges. All 311 Node tests passed.
- Audio offset commit: `036412edac`. Browser and desktop Studio now offer optional peak normalization. The selected audio is scanned once in floating point and one gain is applied to the entire movie. Browser checkpoints can reuse the measurement. The PCM target is −1 dBFS with amplification limited to 24 dB.
- Both Chromium size-target jobs passed with peak normalization and a +250 ms offset. One and two workers produced the same measured decoded peak (−0.54 dBFS on the fixture), preserved 216 coded frames, and stayed under the cap. ADPCM can change the peak during compression. Both native integration tests passed. The full Node suite passed 311 tests, and the additional peak parser test passed separately.
- Next: implement and verify HDR-to-SDR processing, and improve quota allocation for uneven scene complexity. The current bundled WASM FFmpeg has the tonemap filter and lacks zscale, so verify PQ and HLG transfer conversion before exposing a tone-mapping option. Later stages cover SUPER MOFLEX and metadata, CIA building, offline installation, automatic batch workflows, presentation, and final verification. CIA and trailer estimates depend on those format stages.

Physical 3DS and iOS device testing remain pending. Prior short ADPCM hardware evidence is recorded in the README. This milestone supplies software verification only.

## Handoff after the Stage 3–5 milestone

This handoff preserves the previous format, audio, size and recovery milestones. It is a working milestone across the next stages. Full Stage 6 compatibility review remains open.

### Format support

- `super-moflex.mjs` reads `CSXTRA01` after the original MOFLEX stream. It retains unknown sections and validates offsets and packet sizes. `trailer-editor.mjs` adds local metadata, RGB565 poster art, up to 16 SRT/ASS/SSA tracks, a primary language label, and one alternate ADPCM track. An edit downloads a new file with the original stream bytes intact. Imported ASS/SSA is displayed as plain text without its original styling.
- `player-worker.js` plays the selected embedded audio and decodes only the media portion with FFmpeg. Browser MP4 and MKV export can select either audio stream or both. Browser MKV export carries up to four text subtitle tracks. The bundled WASM lacks the MP4 `mov_text` encoder. For MP4 subtitles or more than four exported tracks use the native CLI. Browser alternate audio editing/export and full video export have memory caps.
- `native/super_moflex.py` edits the same trailer and streams the original bytes and retained sections. `native/moflex_convert.py` can export either audio or both and a subtitle language choice in MP4 or MKV, with a temporary output and decode check before publication.
- The layout 2–5 player frame positioning changed to account for packed eyes. The decoder warms a few additional Emscripten threads before combined video/audio decode and multi-track export. The normal encoder and shipped WASM binaries are unchanged. Test both playback and export if rebuilding with a different Emscripten version because thread pool methods come from the loader.
- Format references inspected: Clownsec SUPER MOFLEX `b823a9718`, Clownsec player `585802dcd`, moflex-studio `8ed056444`, clownsec-moflex-encoder `d7c40e813`, Big Top `57dd2bea4`. See the upstream projects for hardware reports. This handoff uses generated test movies and does not claim testing retail files.

### CIA packaging

- `native/cia_builder.py` creates editable ordered JSON projects and builds or previews them with a user-provided local VidInjector9002-CLI. It supports one or several movies, title/publisher, title ID and reserved ID checking, per-movie menu titles and banners, custom icon/banner, automatic frame-derived icon, and preview PNGs. A prebuilt banner binary can provide audio. The final output checks FAT32, title metadata, content section sizes, and hashes. The original Nintendo player only receives the normal media prefix for a SUPER MOFLEX input.
- Tested the native backend built from `FoofooTheGuy/VidInjector9000@7eb44d5fb` with recursive CLI submodules. Generated a single and two-movie CIA and checked the SHA-256 of each CIA content. Automatic icon preview also passed with the real backend. The backend embeds its own `base.cia` and assets. MobiPEG ships neither the backend nor those assets, and uses the backend only when explicitly supplied. The upstream root did not provide an explicit redistribution license for that code and template as a whole.
- Browser CIA **remains unfinished**. The next browser implementation needs an independently distributable packager or explicit redistribution permission, plus a lawful compatible player/template and a layout strategy. A user-selected local template is an option if the packager is distributable. Evaluate OPFS streaming for RomFS/NCCH/CIA sections instead of assembling gigabytes in WASM memory. Validate the project, title IDs, contents and actual 3DS installation. Desktop native audio-from-file banner building, full desktop project GUI, and automatic banner generation are also pending.

### Browser application

- `isolation-sw.js` now also provides an opt-in offline cache. Both engines and the player are cached by version, and the SHA-256 asset manifest is checked before marking the release ready. Installed clients keep their active cache until a replacement verifies and activates. Both Pages root and `dist/` are generated separately because root translation files are forwarding modules. A stale integrity manifest will prevent offline setup.
- Selecting a destination lets the queue save verified files and continue automatically. **Save in this browser** keeps confirmed outputs in private storage for download/delete after reload. Supported browsers can select an external output folder. Manual mode remains available. Folder input imports known video file types. Source files, pending queue order/settings and selected folder permissions are still tab-scoped. Existing movie checkpoints already survive reload with the same source/settings. More complete persistent queue state, pause/skip management, and failure handling remain open.
- Minor copy updates clarify what the web converter does. Full website/native language and accessibility review remains pending.

### HDR and preserved prototype

- The native Studio has an automatic tagged-PQ/HLG-to-BT.709 filter and Mobius, Hable, Reinhard and off choices via `--hdr-mode`. SDR keeps the existing framing filter path.
- Chromium detected both HDR tags once the generated source used `setparams`, but the current WASM filter graph stalled during **Rendering framed source**. Increasing the prewarmed Emscripten thread pool did not resolve it. The web release omits the HDR controls and keeps the previously verified filter path. Compare native and WASM swscale through a minimal in-memory FFmpeg reproducer before wiring up the UI again.
- The exact experimental state, including the two failing Chromium tests, is preserved in local branch `wip/hdr-browser-handoff` at `ad12b17bea16315186a68aa905b0f23a9c5d6cc7`. A full patch relative to `3a36e13b59` is also saved as `mobipeg-browser-hdr-handoff.patch` next to the checkout. Recover the HDR-only portions by inspecting the branch diff for `core.mjs`, `worker.js`, `checkpoints.mjs`, `app.mjs` and the two HDR tests in `tests/browser/upgrade.spec.mjs`. The prototype branch and patch remain outside the public release.

### Commands for continuation

```sh
node scripts/dev-server.mjs
node --test tests/*.test.mjs
MOBIPEG_ENGINE_DIR=dist/engine-simd node --test tests/player-wasm.test.mjs
python3 tests/test_native_resume.py
MOBIPEG_CIA_BACKEND=/path/to/VidInjector9002-CLI python3 tests/test_super_moflex.py
PLAYWRIGHT_BROWSERS_PATH=/path/to/playwright-browsers node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/upgrade.config.mjs
```

Build and test the same local CIA backend with CMake, a C/C++ compiler, and the upstream submodules:

```sh
git clone --recurse-submodules https://github.com/FoofooTheGuy/VidInjector9000 ../VidInjector9000
git -C ../VidInjector9000 checkout 7eb44d5fb
git -C ../VidInjector9000 submodule update --init --recursive
cmake -S ../VidInjector9000/VidInjector9002-CLI -B ../vidinjector-build \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build ../vidinjector-build --parallel
MOBIPEG_CIA_BACKEND="$PWD/../vidinjector-build/VidInjector9002-CLI" python3 tests/test_super_moflex.py
```

Run the commands from the MobiPEG checkout. Tests generate temporary synthetic movies, outputs and CIAs. Use the Linux/macOS native encoder build commands in the README if `native/local/bin/ffmpeg` and `ffprobe` are missing. If Playwright is absent, run `npm install --prefix tests/browser --no-package-lock` and use the local Playwright CLI to install Chromium. The shipped WASM binaries and existing portable native archives were not rebuilt in this milestone.

When changing the web application, update the dependency version queries and the offline `VERSION` in `isolation-sw.js`. Synchronize changed deployment files into `dist/`, keep its real translation tables, then run `node scripts/provenance.mjs`, copy `dist/engine/provenance.json` to `engine/`, and run `node scripts/offline-assets.mjs`. Keep the two WASM engines and their matching JS loaders together. Only rebuild them with Emscripten 4.0.10 if changing codec/filter availability or their sources.

### Handoff verification

- Node regression suite: 312 passed, zero failed or skipped. The separate SIMD WASM FastAudio decoding and playable MP4 export test passed.
- Native integration: five passed with the actual CIA backend, covering trailer integrity and validation, MP4/MKV audio and subtitles, PQ and HLG tone mapping, and single- and two-movie CIA structure and content hashes. Both native resume and audio timeline regressions passed.
- Chromium upgrade suite: all three passed. It imported and edited subtitles and alternate audio, played and exported the edited MOFLEX, completed a real offline conversion and playback, and continued the batch automatically with its downloads available after reload. The output was inspected with ffprobe. External-folder writing was feature-detected but was not exercised with a real directory picker.
- Chromium framing suite: all ten passed, covering scalar and SIMD motion/stereo previews, per-eye cropping, real conversions, advanced overrides, interface language and privacy preferences, and manual queue behavior. Run it with the Playwright command above and `--config tests/browser/framing.config.mjs` in place of the upgrade config.
- Safari/iOS, a physical 3DS, retail MOFLEX inputs, and CIA installation are unverified for this milestone. The earlier physical evidence still applies only to the earlier short ADPCM conversion.

### Priority for the next session

1. Browser CIA path and physical test plan. Use the local native wrapper and validator as requirements references. Avoid redistributing VidInjector/template binaries or upstream assets without permission.
2. Finish browser MP4 subtitle support, large alternate audio editing/export with bounded temporary storage, full metadata and subtitle editing including timing/offsets and source stream extraction, and input stereo detection with ambiguous-case overrides.
3. Persist pending browser batch state and source re-selection, add batch profile and format outputs, and expand scene-aware movie budgets beyond duration-weighted allocations.
4. Execute Stage 6 device and compatibility matrix. Include Safari/iOS installation and resume, Old/New 3DS standard and 3D movie testing, a CIA installation/launch test, Clownsec/standard player behavior, long-seek tests, and measured working memory and playback rates. Finish presentation cleanup after feature parity.

### Browser queue continuation — feature branch, pending integration review

- Queue order, encoding settings, durations, and status are kept in a bounded versioned local-storage manifest. Unfinished jobs require users to reselect the original source files after reload; the site does not store source movie bytes. Reattached jobs keep their saved settings, can retry, and retain ordering.
- Source selection compares filename, byte length and last-modified timestamp when available. This is a convenience check only; the existing checkpoint recovery independently hashes original media before reusing encoded ranges.
- Seven queue unit tests passed in the available local Node runtime. Browser UI regression, integration and physical-device testing remain pending. Keep the branch separate from master pending those checks.

- Follow-up: restored entries now retain correct input-byte estimates. Added a Chromium UI regression for restoring a two-file queue, reselecting both sources, and checking per-file presets. This Playwright test has not yet run in this session.
