# CIA artwork editor recovery and release verification

The recovery starts from PR #6 head `3d2dd949ee131a868a92011d10b25ab7f0bbe333` on `feature/cia-studio-preview-art-20261118`. The previous environment's uncommitted changes were unavailable; the fixes were reconstructed from the branch and browser evidence.

## Changes

- Open the artwork dialog before image decoding completes, show loading/saving/error status, and disable editing while decoding or exporting.
- Give each editor session an identity. Ignore cancelled or superseded decode/export completions, including their error handlers and finalizers. Capture the export destination before awaiting PNG encoding.
- Close decoded bitmaps and clear editor state on cancellation, Escape, dialog closure, successful export and pagehide. A queued close event cannot clean up a newly opened session.
- Keep source and dist copies synchronized. Correct the two stale provenance hashes and regenerate both offline manifests.
- Add deterministic browser regressions controlling decode/export completion order, failure, cancellation, replacement and pagehide; retain exact icon/banner/episode export checks.
- Fix Linux build capability checks to consume diagnostic output, avoiding false SIGPIPE failures from `grep -q` under `pipefail`.
- Use one worker in the form/framing/locale tests; feature-detect OPFS for tests that require it, and test the parallel-conversion explanation when OPFS is unavailable. Chromium still runs the actual OPFS integrations. Linux Playwright WebKit lacks this API. Locale tests use the configured base URL instead of a fixed port.

## Verification

All required local release checks pass. The final full browser runs have zero failures.

| Check | Passed | Failed | Optional skipped |
| --- | ---: | ---: | ---: |
| Complete Node suite: `node --test tests/*.test.mjs` | 379 | 0 | 1 |
| Complete Chromium release selection | 48 | 0 | 13 |
| Complete WebKit release selection | 41 | 0 | 20 |
| Entire artwork suite repeated 20 times in Chromium | 200 | 0 | 0 |
| WebKit pagehide regression repeated with traces | 20 | 0 | 0 |
| Automatic VidInjector player download/build integration | 1 | 0 | 0 |
| Final desktop Chromium / emulated iPhone WebKit smoke checks | 2 | 0 | 0 |

- `node scripts/validate-web-release.mjs` passes: source/dist parity, all root/dist offline hashes, real scalar/SIMD modules, worker release stamps and both provenance manifests.
- Both browser release runs build and independently verify CIA collections with 1, 2, 5, 10, 20 and 27 episodes. Tests verify exact 48×48 icon and 200×120 banner/episode PNG exports and real SMDH/episode texture packing.
- Both browsers pass the real offline conversion/playback test with its HTTP server shut down. The smoke checks also build/download verified CIAs and check every cached dist asset hash (54 assets) and cross-origin isolation.
- Native FFmpeg was rebuilt from the checked-out source. The FastAudio stereo timeline/export integration now passes. Capability-check commands, the Linux builder's existing-binary path and shell syntax checks pass.

The Node skip requires the optional external native CIA backend. The 13 Chromium skips require separately generated 65-second / long indexed-seeking fixtures. WebKit has those same fixture skips and seven additional OPFS-dependent skips; this Linux WebKit build has no OPFS API. All CIA packaging and artwork cases run with fixtures. Unsupported-OPFS messaging is tested explicitly.

Browser testing used Playwright 1.56.1 and the release configuration's complete test selection, with a separately managed development server on port 4174. WebKit runtime libraries were supplied locally in the workspace. Automatic-player upstream requests were bridged through Node's working environment proxy; the browser still validates the pinned resources and builds the actual CIA.

Initial test attempts exposed asynchronous assertions that read artwork before export finished, unsupported-OPFS assumptions, fixed-port assumptions and shared-server lifecycle failures. These were corrected before the final clean runs. One WebKit navigation stalled before the pagehide test began; its isolated 20-repeat trace run and the subsequent complete WebKit run both pass.

Production verification is performed after merge; its deployment SHA and live results are reported separately.

## Scope and fixtures

CIA integration uses a locally generated starter from the project's checksum-pinned upstream VidInjector resources and synthetic MOFLEX inputs. Artwork is a generated red PNG. No player/template/CIA binaries are committed. Native FFmpeg must be rebuilt from this checkout: the restored workspace's previous binary predates the current native sources.

No Azahar executable is installed in this environment, so fresh emulator playback is unavailable under the user's conditional emulator requirement. Historical Azahar reports describe prior commits and are not fresh verification of this branch. Physical console and physical iPhone tests are not claimed; mobile browser checks use iPhone emulation.
