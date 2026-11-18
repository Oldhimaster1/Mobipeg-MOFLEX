# Verified browser release — 2026-11-18

Release cache: `20261118r`. Based on verified development commits `d8a4e879fa` and `8894bd47a0`, preserving their history. No unfinished desktop changes were present or added. The existing native changes in those commits were already tested; this release changes browser cache/import versions, release validation and test tooling, and documentation.

## Release checks

- Full Node suite: **361 passed, zero skipped**, including real generated 1–27-episode CIA packaging and independent native validation, scalar WASM conversion/decoding, genuine tagged PQ/HLG HDR conversion, checkpoint/batch/editor logic and corruption checks.
- Separate SIMD HDR and playback run: **3 passed**.
- Focused Linux WebKit: **5 passed**: SUPER MOFLEX subtitles/alternate audio/MKV export; offline real conversion, playback and CIA generation; HDR controls; real scalar/SIMD encoding and playback.
- The unified Chromium suite covers artwork and actual CIA building at 1/2/5/10/20/27 episodes, saved output recovery, movie conversion, full decoding, crop/stereo previews, compression controls, batch processing, checkpoint recovery, long seeking, editor/export and offline operation. **48 distinct Chromium cases passed**: 42 in the main run plus the six corrected artwork cases. The main run had no skips; its six fixture-related failures were resolved by rerunning with the proper input image.
- The initial CIA artwork assertions used the wrong local input image. Output CIAs passed structure/hash checks, but the red-artwork assertions correctly failed. The six cases were rerun with the required red image and **all six passed**, including extracted movie bytes, menu/title resources, artwork, and restored downloads. No product workaround was made.
- `node scripts/validate-web-release.mjs` verifies root/deployment parity (including the intentional queue-translation re-export), every offline digest, matching service-worker/cache versions, both real WASM binaries, `.nojekyll` and source/engine provenance. This current-source gate is independent of archived media paths. The historical `scripts/validate-release.mjs` remains archival and cannot run without its unavailable original fixtures; it is not represented as passed.

## Deployment and live check

Pages is configured for legacy branch publishing from `master` at `/`, not a custom GitHub Actions workflow. Branch publishing still uses GitHub's internal Pages infrastructure. The actual live origin is https://oldhimaster1.github.io/Mobipeg-MOFLEX/.

Before deployment, a real persistent Chromium profile loaded that origin and saved its complete **20261118h** offline cache. `scripts/verify-live-web.mjs after` uses the same profile to test the normal worker update lifecycle, updated cache, real scalar/SIMD conversions, downloads, full independent native decoding, player startup, two-episode CIA creation/verification and offline conversion. Test usage statistics are opted out. Test videos, templates, CIA outputs and screenshots remain outside Git. The managed network's TLS inspection requires a browser-only test certificate bypass; this does not alter site code or claim to validate its certificate chain.

To reproduce current-source checks:

```sh
node scripts/validate-web-release.mjs
MOBIPEG_CIA_BACKEND=/path/to/local/legal/backend node --test tests/*.test.mjs
MOBIPEG_ENGINE_DIR=dist/engine-simd node --test tests/hdr-wasm.test.mjs tests/player-wasm.test.mjs
# Supply the local fixture/template variables documented in tests/browser/*.spec.mjs.
node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/release.config.mjs
# NODE_USE_ENV_PROXY=1 may be required on managed proxy networks.
node scripts/validate-web-release.mjs https://oldhimaster1.github.io/Mobipeg-MOFLEX/
```

## Remaining limitations

- Real physical iPhone Safari memory pressure, backgrounding, eviction and installed PWA behavior remain untested. Linux WebKit is useful coverage, not an iPhone substitute. Browser storage quotas can prevent saving large outputs; downloads remain available when optional persistence fails.
- CIA packaging requires a locally supplied compatible legally obtained player template; none is distributed. Existing Azahar playback evidence remains valid; no new emulator or physical 3DS playback claim is made for this cache-only release.
- Indexed seeking requires supported validated indexes and safe intra starts/pairs; unsupported files retain forward decoding. Scene-aware allocation improves automatic use of the cap on the measured fixture, but matched-actual-byte quality tied a manually retuned uniform baseline. See `INDEXED_SEEK_COMPRESSION.md`.
- Old offline tabs keep their existing active worker until all tabs for the app close; the prepared update then activates. No user movie data is deleted to force an update.
- Locally refreshed desktop archives are not republished by this web release; native macOS execution remains unverified.
