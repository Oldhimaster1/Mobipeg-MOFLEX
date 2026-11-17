# MobiPEG upgrade progress

Roadmap baseline: `1e46f0db1a` on `master`. This revision already contains desktop and browser MOFLEX export, descriptor-based stereo playback, and optional FastAudio.

## Stage 1

- Browser Studio and desktop Studio enforce the 4,294,967,295-byte limit on completed MOFLEX files. Browser queue estimates show per-file headroom and warn before encoding if the estimated upper bound crosses the limit. Desktop reports equivalent headroom in its conversion log. Estimates remain content-dependent.
- Browser and desktop assembly check media continuity counters, validate indexed sync blocks and descriptor consistency, and detect valid sync blocks omitted from the index. Browser assembly also rejects sparse segment lists.
- Relevant files: `queue.mjs`, `app.mjs`, `movie.mjs`, their deployment copies, `native/moflex_join.py`, and `native/MobiPEG_Studio_V15.py`.
- Regression commands: `node --test tests/*.test.mjs` and `MOBIPEG_ENGINE_DIR=dist/engine-simd node --test tests/player-wasm.test.mjs`. Test vectors use generated media. This milestone changes no codec binaries or compression settings.
- Foundation suite: 304 passed, 0 failed or skipped, including native and WASM export, an actual two-worker WASM join, and structural fault injection. FAT32 is exercised at the numeric boundary without allocating a 4 GiB fixture.

The supported browser and Studio paths use the modified FFmpeg muxer and x264 MobiClip encoder. The browser mounts input with WORKERFS, emits independent OPFS ranges, and verifies the assembled file with separate video and audio workers. The native Studio uses independent FFmpeg processes for ranges, then streams the join through a temporary file. The legacy native research scripts have separate entry points. The browser player uses bounded decoded batches. Existing queue settings and output are tab-scoped. The isolation service worker currently serves the Pages isolation requirement.

Next in Stage 1: persist checksummed browser ranges and reproduce interruption and corruption recovery. Add desktop recovery independently. Extend container validation to packet-level timing and audio boundary fixtures. For later stages, continue in order with whole-movie size targets, scheduling, audio, previews and HDR, then SUPER MOFLEX and metadata, CIA building, offline installation, and automatic batch workflows. CIA and trailer estimates depend on those format stages.

Physical 3DS and iOS device testing remain pending. Prior short ADPCM hardware evidence is recorded in the README. This milestone supplies software verification only.
