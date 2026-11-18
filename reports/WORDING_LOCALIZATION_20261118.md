# Website wording and localization cleanup — 2026-11-18

Baseline: `d8d172b7f0`, the verified published web release. New browser/offline release: **20261118u**, displayed as **2026.11.18u** in Studio.

## Changes

- Guide now explains saved queue order/settings and reselecting original files after reload; verified long-movie checkpoints, re-encoding incomplete/damaged ranges, and storage/eviction limits; automatic batch destinations and saved outputs.
- Corrected audio to **48 kHz**, documented both ADPCM and optional FastAudio, and retained the physical-device compatibility qualification.
- Added practical Guide sections for HDR-to-SDR, still/animated previews, scene-aware versus uniform size allocation, indexed seeking, SUPER metadata/subtitles/alternate audio, the real CIA builder, 1–27 episodes, local templates/artwork/banner audio, project reopening, exact FAT32 limits/collection splitting, offline use and update activation. The Guide remains explicitly English.
- Replaced dated Studio build text and awkward feature/footer phrases. The visible release label is generated from the service-worker version by `scripts/offline-assets.mjs`; `scripts/validate-web-release.mjs` verifies it, preventing the same stale-label problem in future releases.
- Replaced layout-0 activity/report labels. Reports now identify the encoder as `MobiPEG V15 WASM` and include numeric `layout` **6 for 2D** or **1 for left-first stereo**. Downloaded reports from real scalar/SIMD 2D and stereo conversions are checked in browser regressions.
- Added **56 complete catalog rows** in all eight supported interface languages (English, Spanish, French, German, Portuguese, Japanese, Korean, Simplified Chinese). They cover the main headline, new copy, scene allocation, HDR controls/hints, audio controls, motion preview, saved queues/recoveries, batch destinations and navigation. Technical parameter values, source filenames and source track names remain unchanged.
- New all-locale mobile tests exposed WebKit selected-option text painting outside constrained controls. The fix retains native HTML selects, clips the selected text with ellipsis, and supplies an arrow while removing the conflicting native appearance. No page-level overflow hiding was used. All locales fit at 390 px after the fix.
- Root/deployment copies, entry-point/worker/engine release tags, provenance and offline SHA-256 manifests are synchronized. The new catalog is cached offline. **No encoder/native code or WASM binary changes** were made; no binary rebuild was needed.

## Verification

- Full Node suite: **363 passed, zero failures/skips**.
- Full Chromium suite: **50 passed, zero failures/skips**, including real scalar/SIMD conversion, playback, 1/2/5/10/20/27-episode CIA packaging and independent verification, artwork, downloads, project reopening, saved outputs, offline conversion/CIA building, batch/recovery, HDR/editor controls and exact long/stereo seeking. New UI tests validate all eight languages and mobile layout. Real conversion reports check the corrected layout labels.
- After the final CSS fix: **nine focused Chromium checks passed** for localization, framing, previews, actual stereo conversions/reports and preserved parameter values.
- The initial WebKit locale case correctly failed on actual horizontal overflow; five other integration cases passed. Its two copy/Guide cases passed after the fix. A final clean six-case WebKit rerun covers the final source and is recorded below.
- `node scripts/validate-web-release.mjs` passes source/deployment parity, all **53** offline digests, actual engines/provenance, worker/engine release pins and the generated Studio release label. The archived original-fixture gate is not relabeled as passed.

Commands:

```sh
node --test tests/*.test.mjs
node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/release.config.mjs
node scripts/provenance.mjs
cp dist/engine/provenance.json engine/provenance.json
node scripts/offline-assets.mjs
node scripts/validate-web-release.mjs
node scripts/validate-web-release.mjs https://oldhimaster1.github.io/Mobipeg-MOFLEX/
```

The full suites need the same local synthetic fixtures, legal template/backend and browser/library variables documented in the release tests. Test media/templates and screenshots stay outside Git. A persistent live-browser profile saved **20261118t** before publication to exercise the real update to **20261118u**.

Physical iPhone/3DS testing remains unverified for this release; Linux WebKit is not a physical iPhone substitute. Existing Azahar evidence remains the player-compatibility baseline. Firefox could not start in this managed environment during the preceding release; no new Firefox pass is claimed. No general equal-actual-size compression-quality gain is claimed.

Final clean Linux WebKit rerun: **six passed**, including eight-locale mobile layout, the Guide, real SUPER editing/export, offline conversion/playback/CIA creation, and scalar/SIMD conversion with corrected reports. All 53 manifest assets and source/deployment/version checks pass. No native or WASM binary differences from the verified baseline.

## Published verification

Application commit **`8c0064fa92ea4156b03b8862a972b601cd886371`**, cache **20261118u**, was pushed to `master` and reported **built** by Pages. At **2026-11-18 20:32–20:33 UTC**, direct public-site checks confirmed all **53** manifest assets, service-worker/manifest hashes and WASM MIME types. A real Chromium browser checked all eight languages at **390 px**, with size-allocation settings open: headlines/options/stereo hints translated, settings values stayed intact and there was no horizontal overflow. The live Guide contained the updated recovery, 48 kHz and CIA text and no retired queue/audio claims.

The same persistent profile updated its saved **20261118t** cache to **20261118u**. Live scalar/SIMD conversions downloaded valid MOFLEX files and passed independent complete native decoding; the live player started. A live two-episode CIA (**2,574,080 bytes**, title ID **000400000C456700**) passed independent native verification. Restarting the saved profile behind an unreachable network proxy blocked an uncached request while the app still reloaded, converted a real fixture and opened the CIA editor. All **106** observed engine requests carried the expected release tag. Test usage statistics were opted out; fixtures/templates/screenshots remain outside Git.

No additional physical iPhone/3DS or Firefox compatibility claim is made; existing platform limitations remain. The final documentation-only commit preserves these exact tested application assets and cache version.
