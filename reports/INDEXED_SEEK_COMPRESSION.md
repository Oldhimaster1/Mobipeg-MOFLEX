# Indexed seeking and scene-aware size targeting

Baseline: `7009825788`, development branch `development/indexed-seek-compression`.

## Indexed access

The native FFmpeg demuxer and both browser WASM engines now use the validated MobiPEG front table to search near the requested time. A table entry is not treated as a keyframe. The demuxer validates bounds, monotonic entries, sync checksum, clock, and repeated descriptors, scans complete packets for an actual MobiClip intra start, and discards earlier dependent video packets before decoding. Interleaved stereo requires an even-frame intra packet followed by the other eye's intra packet. Audio and video PTS are reconstructed from the 64-bit sync clock and packet-relative clock, using each stream's time base. Packet accumulators are cleared on every probe/reset. A corrupt selected sync fails closed; FFmpeg's unsafe generic byte search is disabled.

Unknown/unindexed files, unsupported multi-video/vendor formats, and inputs without a verified start within the bounded search retain the accurate forward fallback. This is not a promise that every third-party MOFLEX supports rapid access. Long unsegmented stereo chains without fresh two-eye intra starts can still need forward decoding. The new seek path changes no encoded movie, muxer, CIA or executable player format.

Generated 30/60/90/120-minute stress movies were tested at 10%, 50% and 95% of their duration. Every decoded pixel and PCM sample matched a forward-decoded short reference containing the same deterministic motif.

- Native: **0.023–0.133 seconds** per tested seek. At 6,840 seconds in the two-hour file, the same output took **188.404 seconds** through forward decoding versus **0.063 seconds** through the index.
- Chromium scalar/SIMD workers: **0.327–0.701 seconds**, with engine warmup reported separately.
- Linux WebKit scalar/SIMD workers: **1.139–6.295 seconds** under concurrent development load.
- Actual player interface: selecting 6,846 seconds and resuming playback took **6.627 seconds**; the correct decoded red frame and displayed position were verified.

Native regressions compare complete output bytes for 2D, full-SBS, half-SBS, legacy interleaved layout 0, ADPCM, FastAudio, joined ranges, fractional rates, and non-frame-aligned requested times. Unindexed fallback and corrupt-sync rejection are tested. Physical iPhone behavior is not inferred from Linux WebKit.

## Source complexity and budgets

Multi-range browser size-target jobs and native parallel size-target jobs sample source luma at two short locations per range, using at most four 64×36 grayscale frames per sample. Spatial gradients measure texture; interframe absolute differences measure motion activity. This is real source analysis, not a duration/file-size proxy, optical flow or exhaustive shot detection. Both eyes contribute for packed SBS inputs. Native and browser measurements use the same formula, with cross-language tests.

Available video bytes are weighted by measured complexity and coded frame counts, after reserving estimated fixed-codec audio and container floors. Completed ranges spend their actual bytes; unused bytes become available to queued ranges. In-flight caps remain reserved, preventing parallel workers from oversubscribing the target. Eye pairs remain indivisible, the quantizer/codec/quality presets are retained, and final output size checks remain authoritative. Completion order may affect later caps. Existing single-process short-video behavior is preserved.

Analysis is skipped for single-range jobs and cached with resumable work. Cached measurements must match the actual schedule and valid metrics. Sampling is bounded near EOF; an audio-only tail is marked unmeasured instead of causing a valid conversion to fail. Explicit decoder/filter/output thread limits prevent exhausting the browser's fixed pthread pool during analysis.

### Quality and time comparison

The deterministic 12-second 400×240 fixture contains six seconds of static gray followed by six seconds of moving texture/noise, 24 fps. Both methods use the same source, two workers, preset and codec. Complete decoding is verified. PSNR is measured independently with system FFmpeg on the difficult half.

| Allocation | Requested cap | Actual bytes | Difficult-scene PSNR | Encode and verification |
| --- | ---: | ---: | ---: | ---: |
| Uniform baseline | 800,000 | 438,272 | 26.410 dB | 12.929 s |
| Scene-aware | 800,000 | 651,264 | 26.975 dB | 13.616 s |
| Manually retuned uniform, matched actual bytes | 1,228,800 | 651,264 | 26.975 dB | 14.008 s |

The result demonstrates better automatic use of the requested cap and a **0.565 dB** gain for this fixture at that cap, with approximately **5.3%** added measured time. **At exactly matched actual file sizes, measured quality ties. No general equal-byte coding-efficiency improvement is claimed.** The manually retuned baseline required a different cap. A representative real-film/HDR/stereo quality corpus remains necessary before generalizing these results; the original rate-distortion algorithm is unchanged.

## Verification and reproduction

See `INDEXED_SEEK_COMPRESSION_VALIDATION.json` for exact measurements and hashes.

- Node: full suite passed; final tail regression is also covered.
- Native indexed tests: seven tests, including real encodes and byte comparisons; the existing 13 native regression tests also passed.
- Chromium: 19 upgrade/CIA, 10 framing/options/queue, five long/parallel/recovery, eight worker-seek, actual slider, and two analysis/cache tests passed.
- Linux WebKit: eight worker-seek and two analysis/cache tests passed. OPFS support remains unavailable in this Linux build; physical Safari/PWA/background behavior remains unverified.
- Both scalar/SIMD assets are rebuilt, source/deployment copies synchronized, offline manifests regenerated, and provenance includes the modified sources.
- Linux portable smoke passed. Windows portable smoke under Wine passed 2D/full-SBS/half-SBS, selected audio, complete decoding and output protection. macOS binaries were cross-built and structurally checked, with ARM64 ad-hoc page hashes verified; macOS/GUI execution is unverified.
- Cross packages now contain all local Python modules. The isolated launcher adds only the trusted application directory to import its modules, rather than the caller's working directory or `PYTHONPATH`.

Commands:

```sh
python3 tests/test_indexed_seek.py
node --test tests/*.test.mjs
MOBIPEG_ENGINE_DIR=dist/engine-simd node --test tests/player-wasm.test.mjs
python3 scripts/benchmark-seeking.py GENERATED_FIXTURE_DIRECTORY --baseline
python3 scripts/benchmark-compression.py
MOBIPEG_SEEK_FIXTURES=GENERATED_FIXTURE_DIRECTORY node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/seeking.config.mjs
node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/complexity.config.mjs
```

Use the previously documented browser cache/library setup. Set `MOBIPEG_TEST_BROWSER=webkit` for WebKit. Native CIA integration tests require the existing local legal backend/template variables. `scripts/stress-long-movie.py` produces the deterministic long fixtures from the six-second source clips. `MOBIPEG_FORWARD_SEEK=1` selects the old decoder behavior for controlled comparisons; `MOBIPEG_UNIFORM_BUDGET=1` selects the native uniform allocator for the compression comparison.

For a demuxer-only change, `EMSDK=/path/to/emsdk bash scripts/relink-wasm.sh` rebuilds changed FFmpeg objects and relinks the already built scalar/SIMD codec archives, avoiding unnecessary codec reconfiguration. The full initial build remains a prerequisite.

Rebuilt portable archives are local development artifacts. Existing published release assets have not been replaced. No sample videos, templates, credentials or private machine paths are committed. No new Azahar run was necessary for these decoder/allocation changes: the proprietary player, CIA format, muxer and codec are unchanged, and existing Azahar evidence remains the compatibility baseline. Physical 3DS compatibility is not newly claimed.
