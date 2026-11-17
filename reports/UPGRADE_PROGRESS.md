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

Remaining Stage 1 work includes packet-level and A/V boundary validation, a checkpoint browser and management controls, and estimates for future container features. Stages 2–6 cover whole-movie size targets, dynamic scheduling, audio, animated previews and HDR, then SUPER MOFLEX and metadata, CIA building, offline installation, automatic batch workflows, presentation, and final verification. CIA and trailer estimates depend on those format stages.

Physical 3DS and iOS device testing remain pending. Prior short ADPCM hardware evidence is recorded in the README. This milestone supplies software verification only.
