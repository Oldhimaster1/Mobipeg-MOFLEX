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

- Browser checkpoint management lists recoverable OPFS jobs and stored-byte estimates, and offers confirmed deletion under the per-job Web Lock. It never loads video payload bytes for display. Four focused Node tests passed locally; browser UI verification is added but not run in this session.

## Browser HDR + CIA project integration (November 17, 2026)

### HDR-to-SDR encoding — implemented on feature branch

- Web Studio now exposes HDR transfer auto-detection and manual PQ/HLG selection, plus Off/Mobius/Hable/Reinhard.
- The browser worker generates a 33×33×33 3D LUT locally (BT.2020 PQ/HLG -> display-referred BT.709 SDR), mounts it into FFmpeg WASM via WORKERFS, and applies `lut3d` before picture framing and MobiClip encoding. The filter is also used by still/motion previews and multiple-worker movie segments. Existing SDR filter arguments are unchanged and older stored settings still validate.
- The LUT approach avoids the earlier browser `tonemap` floating-filter stall. It approximates a 100-nit SDR / 1000-nit HDR reference and must not be described as certified professional color grading.
- Actual scalar WASM filter tests produced and decoded 320×240 MobiClip MOFLEX from generated 10-bit PQ and HLG FFV1 inputs (both 24 frames). The committed `tests/hdr-wasm.test.mjs` repeats the real encode-and-decode path using the checked-in engine. Six LUT operation combinations were separately checked for finite/neutral output in JavaScript.
- **Pending:** run the complete Node suite in a fresh checkout, the committed HDR WASM regression in CI/desktop, browser Playwright, mobile Safari and real 3DS tests. Do not call the full workflow hardware-verified.

### Browser CIA project editor — implemented, CIA packaging still native only

- `cia.html` and `cia.mjs` let users choose/reorder up to 27 locally inspected MOFLEX movies, set per-episode titles and banner paths, set global banner/icon, title ID and publisher, then export a `project.json` that matches `native/cia_builder.py`.
- `cia-project.mjs` validates title length and C0000–EFFFF unique ID, rejects unsafe/duplicate file names, checks file-size budgets before native packaging, and does not copy media into the JSON. A native builder with a separately obtained VidInjector9002-CLI produces and verifies the CIA.
- **Not implemented:** direct in-browser CIA packaging into a playable `.cia`. Upstream backend and base assets cannot currently be bundled without determining redistribution rights. Streaming RomFS/NCCH packaging and compatible source assets remain future work. No user videos or third-party templates have been committed.
- Source and `dist/` are synchronized. The offline manifest now includes the CIA builder, project schema and HDR LUT and uses version `20261117z`.

### QA / handoff

- Run `node --test tests/hdr-lut.test.mjs tests/cia-project.test.mjs` and `node --test tests/hdr-wasm.test.mjs`.
- Then `node --test tests/*.test.mjs` (including pre-existing tests), the full Playwright suite and physical console tests.
- On any web file change, synchronize source and `dist/` and regenerate `node scripts/offline-assets.mjs`; verify offline hashes before publishing.

## Review of master 288da36c

Work continues on `development/browser-cia-completion`. This review is incomplete and must not be treated as the requested final project validation.

- Fixed CIA size estimation to validate every individual byte count before summing. Negative sizes, fractional counts and string coercions previously bypassed validation. Root and deployment copies match.
- Updated framing regression fixtures to explicitly disable HDR when testing the three-operation SDR preview path. The added HDR metadata probe had made two old mocks fail before they reached their intended assertions. Actual HDR remains enabled by default in the application.
- Refreshed offline manifests and advanced the service-worker cache version to `20261118a`.
- Full Node run passed 341 tests with zero failures or skips, including genuine PQ/HLG WASM encoding and decoding. The separate SIMD FastAudio decode/MP4 export test passed. Ten Chromium framing tests passed, including scalar/SIMD stereo and motion previews, real conversion and serial queues.
- Five native SUPER tests passed with the real external VidInjector backend, including single/two-movie CIA generation, hashes, exports and HDR. Two native recovery/audio tests and six MOFLEX preflight tests passed.

### Browser CIA work still required

No browser packaging backend has been implemented by this review. `cia.mjs` still exports JSON. Native packaging uses `VidInjector9002-CLI/sources/archive.cpp`, which writes the embedded `base_cia_data` to a temporary `base.cia`. Shipping that tool unchanged as WASM would also ship the embedded application/template. Its root redistribution permission is unresolved. This is a blocker to redistributing that particular backend, rather than evidence that browser CIA creation is technically impossible.

The practical implementation route remains a distributable RomFS/NCCH/CIA writer with a user-selected, locally obtained compatible player template. It must rebuild RomFS file tables and hashes for the selected movie layout, preserve the executable/ExeFS, update extended-header and NCCH IDs/hashes and TMD content records, and produce matching ticket metadata and content bitmap. Simply appending MOFLEX bytes to a CIA or changing its manifest cannot satisfy these requirements. Validate against real single- and multi-movie native outputs and inspect executable contents before offering a build button. Do not substitute synthetic structure-only packages for installable applications.

Browser CIA implementation, exhaustive repository review, Firefox/WebKit runs, physical 3DS installation/playback, measured mobile memory, reference color accuracy and final UI polish remain unfinished. This review has no new hardware evidence or controlled performance comparison. Build/test commands in the preceding sections still apply. Keep this work on its development branch until the requested browser backend and relevant integration tests are ready.

The first Chromium upgrade run passed seven tests and exposed a real damaged-queue recovery bug. `renderQueue()` hid the entire panel when the queue had no valid entries and cleared the recovery explanation. Both root and deployment copies now keep the panel and explanation visible while `queueRestoreError` is set. Existing discard confirmation and storage preservation logic are retained.

After the fix, all eight Chromium upgrade tests passed in 28.4 seconds, including real offline conversion, SUPER playback/MKV export, batch saving/reload and damaged queue discard. Focused Node queue/schema/framing tests passed 17/17 after the application fix. Ten framing browser tests took 1.1 minutes under concurrent test load. These are test elapsed times, not encoder speed measurements. Only Chromium is installed in this workspace; Firefox/WebKit and actual iPhones remain untested.

## Functional browser CIA packaging

`cia-packager.mjs` now rebuilds actual executable CIA content using only a user-selected local compatible CIA. It parses a decrypted single-content title, preserves the player's executable and layout resources, replaces movie payloads in the existing RomFS metadata tree, updates episode title CSV and SMDH title/publisher fields, rebuilds all three IVFC integrity levels, updates extended-header IDs, NCCH size and hashes, ticket/TMD IDs, TMD content and content-info hashes, and assembles the CIA. `cia-sha256.mjs` hashes Blob contents with 1 MiB reads. Movies stay in Blob slices. Executable prefix is capped at 16 MiB. No third-party source or template was copied into the repository.

The actual editor has a local template selector and Build CIA button. Prepared SMDH icons and CBMD banner binaries, including any contained audio, are supported. Existing menu resources and episode artwork are preserved. Browser integration generated and downloaded an actual CIA, and the independent native verifier accepted its content hash and requested title ID.

Native-reference integration generates real single- and two-movie templates from synthetic MOFLEX, rebuilds each using JavaScript, verifies both with Python, extracts both with VidInjector and compares every movie byte. It also builds with prepared custom icon/banner assets and tests corruption and slot-count/template rejection. Run `MOBIPEG_CIA_BACKEND=/path/to/VidInjector9002-CLI node --test tests/cia-packager.test.mjs`. No proprietary template/output is committed.

Remaining implementation limits are explicit. Template slot count must match the project exactly. Switching between single-player and collection-player executable/layout modes requires a suitable matching template. PNG/BMP-to-SMDH and banner generation, edited per-episode artwork, OPFS output staging, full inner IVFC validation of arbitrary incoming templates, tested 3–27 episode builds and multi-gigabyte stress testing remain open. The source template's content hash and NCCH section hashes are verified. Browser-generated outputs are structurally tested but have no physical 3DS installation/playback evidence. Preserve this work on the development branch until remaining feature requirements and stress/device validation are resolved.

Verification for this packaging milestone passed 342 full-suite Node tests with the real native backend enabled, plus the subsequently added independent SHA-256 boundary-vector test. Both focused packaging/hash tests passed after the final metadata-bound validation. Nine Chromium upgrade tests passed in 31.9 seconds, including real CIA download through the editor and independent Python verification. The single real CIA UI test initially passed in 1.1 seconds on this host with a small generated two-movie fixture. This timing is not a movie-length performance benchmark. No new physical hardware compatibility claim is made.

## Reusable 1–27 episode collection templates

The prior exact-slot restriction is removed for recognized collection-player templates. `cia-romfs.mjs` independently reconstructs RomFS directory entries, sibling/child pointers, file entries, UTF-16 names and hash bucket chains for a changed file tree. `cia-packager.mjs` replaces the movie/thumbnail list, updates the `# 動画の数` setting, generates the ordered `movie_title.csv` and `movie_bnrname.csv`, and updates the save-data ID in settingsTL alongside ticket/NCCH/exheader/TMD IDs. This uses the existing collection executable and menu resources unchanged. A single-player template still rejects multiple movies. Recognition requires numbered movie slots, a collection count setting, thumbnail list and a first-episode BIMG. Native generation references use these same resources and settings. No proprietary source/assets were added.

One compatible two-episode collection template was rebuilt into real CIAs with 1, 2, 5, 10, 20 and 27 episodes. Independent native verification and VidInjector extraction passed for every size, every movie byte and title row, the episode count, unchanged executable bytes and every original menu layout resource. Prepared per-episode BIMG thumbnails matching the template format are supported. Custom thumbnails are independently extracted and byte-compared. These are generated software fixtures, not physical console evidence.

The editor accepts prepared per-episode BIMG files. PNG/BMP thumbnail conversion remains pending. The optional oversized-collection splitter preserves input order, reserves the full template size plus 64 MiB for each part, and assigns consecutive unique IDs within the permitted range. Each output still receives the exact final FAT32 check. One individually oversize movie is rejected. The splitter has not been stress-tested with multi-gigabyte real media; it is conservative and can split sooner than strictly necessary. Browser policies can require permission for multiple downloads.

RomFS hashing now reads 1 MiB chunks and stores hashes in one contiguous array, avoiding one retained JavaScript object per 4 KiB block. At the FAT32 boundary the first hash table is about 32 MiB. OPFS output staging is still absent. Do not claim measured iPhone memory bounds or console selection/playback compatibility.

Final collection validation passed all 344 Node tests with no failures/skips (32.2 seconds). Fourteen Chromium upgrade tests passed (1.1 minutes), including actual builds/downloads for all six collection sizes from the same local two-episode template, followed by independent native verification, extraction and exact per-episode payload/title-order comparisons. The native-reference test additionally compares executable bytes and all retained layout resources and custom per-episode thumbnails, and preserves/rejects single-player template behavior appropriately. Split-budget tests cover order, exact numeric boundaries, individually oversized inputs and exhausted title-ID ranges. Multi-gigabyte split downloads and physical selection/playback remain unverified. Root/dist copies and offline integrity manifests were synchronized at cache version `20261118c`.

## CIA image conversion and private output staging

`cia-artwork.mjs` now converts local PNG/BMP/JPG artwork into template-preserving SMDH icons and BIMG episode thumbnails. Browser canvas performs center-cropped resizing and alpha compositing; the independent texture encoder packs little-endian RGB565 into 8×8 Morton tiles. Icons retain existing SMDH settings while replacing 24×24 and 48×48 textures. Episode thumbnails preserve the original BIMG header and fill the 200×120 image region of the 256×128 texture. Prepared binaries remain supported. File input is limited to 32 MiB and decoded dimensions to 40 megapixels; decoding happens before the dimension check, so these checks do not establish a peak memory guarantee on iOS. Image-based HOME Menu banner generation remains unfinished; prepared CBMD banners/audio still work.

`cia-output.mjs` streams a completed CIA Blob into a randomly named file in `mobipeg-cia-outputs` using OPFS writable streams. The user can enable staging before downloads. Output size is checked after closing, partial files are removed on failure, and saved files can be downloaded or deleted from the builder after reload. Unsupported browsers disable the storage option. This stages the final output; it does not convert the entire packager into an OPFS random-access writer. Existing bounded hashing and Blob-backed source slices remain in use.

Verification passed all 345 Node tests with the real native backend enabled (36.4 seconds). Fourteen Chromium upgrade tests passed with PNG artwork and OPFS staging enabled for all six collection sizes (1.4 minutes). Native extraction confirmed red RGB565 data in both the SMDH icon and first episode BIMG, in addition to prior content/title/payload verification. A separate real build/download/reload test confirmed saved CIA availability after reload (6.5 seconds total). Unit tests verify tile ordering, RGB565 channels and transparent-to-white compositing. The initial PNG test expected a full-scale red value, but the FFmpeg-generated fixture is slightly below full scale; its valid RGB565 expectation was corrected. No product behavior was changed to satisfy that test.

Next priorities remain image-based HOME Menu banners, measured multi-gigabyte builds and split downloads, broader Firefox/WebKit/Safari coverage, project reopening and converter integration, and the remaining metadata/stereo/compression/batch/presentation work from the roadmap. Physical 3DS installation, collection navigation and playback remain unverified. Keep the branch separate from master until release verification is complete. Offline cache version is `20261118d`, with all new source/deployment assets in both manifests.

The final focused Chromium check additionally downloaded a real staged CIA, reloaded the page, confirmed its saved download entry, accepted the explicit deletion dialog and verified the entry disappeared. It passed in 8.0 seconds total. Focused artwork/schema checks passed six tests after the final format-validation changes.

## Image-based HOME Menu banners and first console test kit

`cia-banner.mjs` reads the selected local template's CBMD graphics offsets, safely decompresses bounded LZ11 CGFX models, finds a compatible 256×128 RGB565 texture through the model dictionary, substitutes the locally converted image and repacks the CBMD while retaining model/animation resources and existing audio. It rejects missing or ambiguous compatible textures. Repacking uses literal LZ11 streams, which preserve graphics but can increase banner size. Prepared CBMD inputs remain supported. No model/template binary or upstream source was copied into the repository.

`cia-banner-audio.mjs` accepts short mono/stereo PCM16 RIFF/WAVE at 8–48 kHz, up to ten seconds and 2 MiB. It writes PCM16 CWAV with aligned planar channel buffers and updates the banner audio offset. Existing audio is retained when no WAV is selected. Standard FFmpeg on the host lacks CWAV demuxing, so decoding was independently checked with vgmstream-cli r2168, obtained only as a temporary local test tool. Both generated one-second, 32 kHz mono and stereo CWAVs decoded successfully and matched every original PCM sample. Neither tool binaries nor generated third-party templates are committed.

All 347 Node tests passed with the real native backend enabled (32.0 seconds). Fourteen Chromium upgrade tests passed (1.1 minutes), including 1/2/5/10/20/27-episode builds with a converted HOME Menu banner and optional WAV. VidInjector extracted the CIAs and rendered banner previews independently; the red artwork was verified from preview pixels. The generated CWAV was present in extracted banners. LZ11 round-trip/corruption and exact PCM16 channel/sample tests also passed. Final focused tests passed after the raw-banner memory bound. Physical banner playback remains unverified.

`scripts/prepare-cia-device-test.py` generated and fully decode-verified two six-second 320×240/24 fps ADPCM MOFLEX files. Episode one has a red background and 440 Hz pulses, episode two blue and 880 Hz pulses; white flashes coincide with the pulses. Each output is 323,584 bytes. Their hashes are `1f7b82cf347c96f897b239ee73fa7ae38d6288d6fefa33848b07cfba062a3d0e` and `dcccf064096dcf14516d7db8b9e2801719e87700db685a2e12062946b11f8f6c`. The files and project are in the workspace's `mobipeg-device-test` directory outside Git. `reports/CIA_DEVICE_TEST.md` provides the precise installation/menu/audio/seek checklist. Producing a distributable console-test CIA requires the user's own legally obtained collection-player template; the reference template used in automated tests is not redistributed.

Keep the development branch until the console result is available. Follow-up priorities are measured multi-gigabyte packaging/split downloads, Safari/iPhone/Firefox testing and final interface polish. No new large-file or physical-device claims are made. Offline assets are synchronized at version `20261118e`.

## Azahar runtime acceptance and integration

The user explicitly accepted Azahar runtime verification as this milestone's release gate. The official Azahar 2126.2 AppImage was executed with software Mesa, a virtual display, a real window manager and captured PulseAudio output. Browser-generated CIAs were actually installed and launched. Two-episode menu navigation, changing video frames, distinct 440/880 Hz audio, seeking, menu returns, normal exit and relaunch/replay passed. Collections with 5, 10, 20 and 27 episodes played first/middle/last entries. Screenshots show the selected player titles and advancing time counters, including episode 26 in the 27-entry collection. See `reports/AZAHAR_VALIDATION.md` for scope, reproduction and evidence. Failed setup/OCR/controller attempts were excluded and corrected before recording passes.

Runtime testing found and fixed stale player-facing long-title/publisher settings and reversed interleaved eye presentation. Left-first stereo now uses layout 1 in both browser and native wrappers. The source pixels and timing remain unchanged; the freshly encoded corrected stereo fixture was byte-identical to the descriptor-corrected fixture that showed red in Azahar's left eye and blue in its right eye. Native/browser player and export interpretation now follows the verified interleaved order. Stereo checkpoints use a distinct identity to prevent joining old-layout ranges to corrected ones. 2D checkpoint identities remain compatible. A pixel-color regression now checks exported left/right eye content as well as timing and FastAudio.

The original 320×240 fixture exposed an unfilled edge in the reference player. The device fixture generator now uses 400×240, and the CIA editor recommends this tested geometry for other sizes. The format/encoder still supports other resolutions, whose behavior in this template player is not claimed as validated. Existing layout-0 files created left-first by older MobiPEG versions may need re-encoding for correct stereo in this player. The portable archives were not rebuilt; source Studio and the website use the corrected settings. Codec and WASM binaries did not need rebuilding because the supported muxer flag changed at invocation time.

Source/distribution modules, import versions, engine provenance and offline manifests are synchronized at `20261118f`. Physical 3DS compatibility, multi-gigabyte stress tests, Safari/iPhone behavior and longer-movie runtime checks remain unverified. These are documented follow-up work, rather than physical-hardware blockers to the user-accepted Azahar milestone.

Final integration checks passed 348 Node tests, the additional SIMD FastAudio/MP4 test, 13 native tests, 14 Chromium upgrade tests, 10 Chromium framing tests and all five long-movie Chromium cases. The two fixture-dependent long-movie cases were rerun with a generated 65-second stereo input after the initial no-fixture run skipped them; both scalar checkpoint recovery and SIMD two-worker conversion completed successfully. There are 29 passing Chromium cases across the three configurations. The native FastAudio stereo export regression verifies both eye colors after the layout correction. Validation facts and the evidence archive checksum are in `reports/azahar-validation.json`. The user-approved Azahar release gate is satisfied for the documented short-fixture scope, allowing this milestone to be fast-forwarded into master while retaining the explicit device/large-file limitations.

## Browser reliability follow-up — 2026-11-18 (in progress)

Branch: `development/browser-reliability`, based on verified master `a7ffa9f302`.
The previously recorded Azahar results remain the compatibility baseline; these changes do not alter CIA packaging, player executables, codec binaries, stereo descriptors, or compression settings.

Implemented:
- CIA JSON projects can be reopened with locally reselected movies and artwork. Order, episode titles/thumbnails, HOME Menu metadata, icon/banner, optional banner audio and automatic splitting settings survive a round trip. Imports validate the shared native schema and safe filenames, reject missing/ambiguous files and oversized JSON, and inspect every MOFLEX before replacing the existing editor. Movie bytes are not embedded in JSON. Template selection remains explicit and local.
- The CIA editor can add completed batch conversions directly from OPFS, without an intermediate download and reselection. Files are naturally sorted and remain individually reorderable. This requires saving batch conversions in the same browser/origin first.
- CIA storage checks available quota before copying. A failed save cleans up the partial file and preserves the completed CIA for direct download; optional persistence no longer discards a successfully built result.
- Reproduced a real WebKit shared-WASM-memory growth failure: pthreads trap with `RuntimeError: Out of bounds memory access`, while Emscripten unwinds the main call with status zero and empty output. Reserving the working heap before thread startup fixes the tested decoding/encoding paths. WebKit reserves 128 MiB of linear memory per command, or 256 MiB for multi-input export; Chromium keeps its original default. This is a linear-memory reservation, not a measured physical-memory guarantee. Large sources can still grow beyond the reservation and require further testing. No WASM rebuild was needed.
- Playwright upgrade tests now accept `MOBIPEG_TEST_BROWSER=webkit`. CIA packaging tests still build and independently verify downloadable CIAs when OPFS is unavailable. Storage-specific tests explicitly skip when the tested browser has no OPFS API.
- Added an optional actual file-backed multi-gigabyte SHA-256 stress benchmark, `node --expose-gc scripts/stress-cia-hash.mjs [bytes]`. It checks the complete result against independent Node crypto and measures RSS and read bounds. It uses synthetic data, not user media.

Verification so far:
- Full Node suite: **353 passed, zero skipped**, with the local native CIA backend enabled. Separate SIMD WASM test: **1 passed**.
- Chromium upgrade suite: **17 passed**, including real artwork/audio CIA builds for 1/2/5/10/20/27 movies and independent native verification, scalar/SIMD conversion and independent full decode, offline conversion/playback, recovery, project reopening and multi-track MKV export. A subsequently added direct OPFS-to-CIA integration test also passed separately. Chromium framing/options/batch regressions: **10 passed**.
- WebKit focused checks: project reopening, real scalar/SIMD conversion and playback, SUPER editing with alternate audio/subtitles and MKV export, and a two-episode CIA build passed. Complete WebKit run: **14 passed, 3 OPFS tests skipped, 1 failed** (offline navigation, described below). Real CIA collection builds with converted artwork and WAV audio passed at all six sizes, with independent native verification.
- Actual **2,147,483,665-byte** file-backed hashing: **102.383 seconds / 20.003 MiB/s**, independent digest matched, **2,049 reads**, maximum read **1,048,576 bytes**; process baseline RSS **82,284,544 bytes**, peak RSS **134,168,576 bytes**. This measures the hash implementation in Node, not full CIA packaging, browser RSS, movie decoding or iPhone behavior.

Environment limitations and work still required:
- Linux Playwright WebKit 26.0/build 2215 is not an iPhone or macOS Safari. Its `navigator.storage` is absent even with a secure, cross-origin-isolated localhost page, so it cannot test OPFS checkpoints, saved CIAs or saved batch outputs here. Chromium covers those paths. Physical iPhone storage pressure, eviction, background suspension and Home Screen installation remain unverified.
- WebKit's automated `context.setOffline(true)` followed by navigation failed with an internal WebKit error on the baseline. This remains under investigation; do not claim Safari offline conversion passed.
- Native regression: **13 passed** (2 checkpoint/resume, 5 SUPER MOFLEX, 6 preflight). Separate SIMD WASM: **1 passed**. Multi-gigabyte full CIA packaging, near-FAT32 real collections, new scene-complexity allocation, long-duration seek/audio stress, broader batch controls and SUPER editing improvements remain separate follow-up work. Native portable distributions are unchanged because no native code changed.

Reproduction uses the existing commands documented above. Browser command: `PLAYWRIGHT_BROWSERS_PATH=<browser-cache> MOBIPEG_TEST_BROWSER=webkit node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/upgrade.config.mjs`. Supply local legally obtained template/movie paths using the existing `MOBIPEG_TEST_CIA_*` variables for real CIA tests. This Linux environment required locally extracted shared libraries and preserving their library search path in the external Playwright launcher; those environment changes are not shipped as application changes. Refresh distribution copies and run `node scripts/provenance.mjs` and `node scripts/offline-assets.mjs` after changing shipped assets.
