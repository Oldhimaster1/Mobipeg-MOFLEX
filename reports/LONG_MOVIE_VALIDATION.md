# Long-movie preview validation

This preview keeps all media local. No video is sent to a server.

The browser now encodes chapters of at most 30 seconds into OPFS and joins them
with a rebuilt front index. Only chapter-sized encoded outputs are kept in WASM
memory. Final assembly reads 512 KiB at a time from OPFS, and the completed movie
is decoded from a file-backed input. This bounds output buffering by chapter size;
it does not bound source-decoder memory for every resolution/codec or guarantee
that an iPhone can decode every input. The ordinary short-file path remains available.
Long mode is selected automatically when browser metadata reports more than three
minutes and OPFS is available; users can select it explicitly for other inputs.

Long mode uses 48 kHz audio. Chapter boundaries are aligned to both whole video
frames/stereo pairs and 256-sample ADPCM blocks, including fractional frame rates.
This prevents independent chapter padding from accumulating into audio drift.
Only the final chapter may need a partial-block audio pad. A 4 GiB FAT32 output
limit and a browser-storage preflight prevent producing an unusable oversized file.

The native converter no longer has a fixed 30-minute encoding deadline. Both
native and web filters preserve source pixel aspect ratios, including anamorphic
widescreen. Half-SBS doubles the incoming pixel aspect ratio before fitting each
eye. Audio language/track selection is available in both interfaces; native CLI
users can inspect `--list-audio-tracks -i FILE` and choose `--audio-track N`.

## Reproducible checks

- `node --test tests/core.test.mjs tests/movie.test.mjs`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s native/V15 -p test_studio.py -v`
- `node tests/long-movie.mjs /tmp/mobipeg-long-results`
- Install `tests/browser/package.json` dependencies and Chromium, run
  `python3 tests/browser/generate-fixture.py --output /tmp/mobipeg-browser.mp4`,
  then set `MOBIPEG_BROWSER_FIXTURE=/tmp/mobipeg-browser.mp4` and run
  `npx playwright test --config tests/browser/long.config.mjs`.

The long-timeline test uses a genuinely encoded synthetic audiovisual chapter,
repeated to create 5-, 10-, 30-, 60-, 90-, 120-, and 180-minute timelines. Every result
passed complete video and audio decoding, exact frame count, audio duration within
6 ms of video, and a late seek hash comparison against the corresponding chapter
frame. The 120-minute case contains 172,800 frames and is 413,052,928 bytes. An additional
180-minute case passed the same checks with 259,200 frames and 619,577,344 bytes.
Machine-readable results are in `long-movie-validation-20261116.json`.
These are container/timeline stress tests, not full-length diverse movie encodes.
Both rebuilt scalar and SIMD binaries also passed real two-second 2D, full-SBS,
and half-SBS conversion and complete decode checks under Node. Chromium completed
a 65-second half-SBS movie with each engine: three OPFS chapters, 3,120 coded
frames, selected-language audio confirmed by its tone, verified download, and
cleanup of the stored movie. Clean end-of-video is distinguished from encoder
errors so an audio tail longer than the video cannot force an extra empty chapter.
Both WASM engines also passed an explicit seek-to-EOF regression and Chromium
conversion with a 65-second video/66-second audio fixture. The existing Chromium
short-conversion, cancellation and mobile-layout tests also passed.

Native tests generate their previously missing fixtures in temporary directories;
no private video is required or committed.

## The historical duration field

The front index has a 32-bit microsecond duration field, which cannot represent
more than 71 minutes 35 seconds. Both native output and browser joining now
saturate this field at UINT32_MAX instead of wrapping it. Frame count, seek-entry
microseconds, offsets, and block sync timestamps retain their wider representation.
Our software decoder uses frame counts and timestamps and decodes/seeks beyond
that boundary in the 90-/120-minute tests. Saturation is not evidence that Nintendo's
player interprets this field the same way. The UI identifies this limit for long outputs.

Physical 3DS playback/seeking beyond 71 minutes, long stereo playback, iPhone
Safari memory limits, tab suspension, and recovery after closing a tab remain
unverified. Closing the tab does not resume a conversion. No physical-device
compatibility claim is added by these software checks.

## Local desktop builds

GitHub Actions is not used. Linux was built and its portable executable passed
real conversion/decode and file-protection smoke tests. Windows was cross-built
locally with Zig and tested under Wine using the bundled Python/Tk runtime and
native launcher: 2D, full-SBS, half-SBS, selected-language audio, complete decode
and existing-output protection. Paths with spaces are covered. The full native
suite's generated-input step requires lavfi, which is intentionally absent from
the cross-build device profile; Windows package tests use a generated Linux
fixture instead. The full 19-test native suite passes on Linux without skips.

Intel and Apple Silicon Mac executables were cross-built locally. Architecture
and system-only dynamic imports were checked. ARM64 ad-hoc signature page hashes
were verified; Intel binaries are unsigned. The matching standalone Python/Tk
runtimes were checksum-verified against official release metadata. Mac execution
and GUI interaction have not been tested. See native/PORTABLE_BUILDS.md.
