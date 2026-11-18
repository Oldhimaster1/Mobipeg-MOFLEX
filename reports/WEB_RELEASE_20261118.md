# Verified browser release — 2026-11-18

Final release cache: `20261118t` (supersedes the intermediate `20261118r` deployment). Based on verified development commits `d8a4e879fa` and `8894bd47a0`, preserving their history. No unfinished desktop changes were present or added. The existing native changes in those commits were already tested; this release changes browser cache/import versions, explicitly pins encoder and decoder JS/WASM/pthread script URLs to the same release, adds release validation/test tooling, and updates documentation. This prevents non-offline users from temporarily reusing an old unversioned engine through HTTP caching.

## Release checks

- Full Node suite: **361 passed, zero skipped** (repeated successfully after final engine URL pinning), including real generated 1–27-episode CIA packaging and independent native validation, scalar WASM conversion/decoding, genuine tagged PQ/HLG HDR conversion, checkpoint/batch/editor logic and corruption checks.
- Separate SIMD HDR and playback run: **3 passed**.
- Focused Linux WebKit: **5 passed**, repeated successfully on the final pinned version: SUPER MOFLEX subtitles/alternate audio/MKV export; offline real conversion, playback and CIA generation; HDR controls; real scalar/SIMD encoding and playback. A further WebKit SUPER editor/export recheck passed after pinning its alternate-audio worker URL too.
- The unified Chromium suite covers artwork and actual CIA building at 1/2/5/10/20/27 episodes, saved output recovery, movie conversion, full decoding, crop/stereo previews, compression controls, batch processing, checkpoint recovery, long seeking, editor/export and offline operation. **48 distinct Chromium cases passed** in the initial release run (42 plus six corrected artwork cases). The complete final-version rerun also checks all requested JS/WASM engine release tags during real conversion/playback; final results are recorded below.
- The initial CIA artwork assertions used the wrong local input image. Output CIAs passed structure/hash checks, but the red-artwork assertions correctly failed. The six cases were rerun with the required red image and **all six passed**, including extracted movie bytes, menu/title resources, artwork, and restored downloads. No product workaround was made.
- `node scripts/validate-web-release.mjs` verifies root/deployment parity (including the intentional queue-translation re-export), every offline digest, matching service-worker/cache versions, both real WASM binaries, `.nojekyll` and source/engine provenance. This current-source gate is independent of archived media paths. The historical `scripts/validate-release.mjs` remains archival and cannot run without its unavailable original fixtures; it is not represented as passed.

## Deployment and live check

Pages is configured for legacy branch publishing from `master` at `/`, not a custom GitHub Actions workflow. Branch publishing still uses GitHub's internal Pages infrastructure. The actual live origin is https://oldhimaster1.github.io/Mobipeg-MOFLEX/.

Before deployment, a real persistent Chromium profile loaded that origin and saved its complete **20261118h** offline cache. The intermediate deployment `0923ffc53c` served all 52 manifest assets with matching SHA-256 values and correct WASM MIME types. Its live scalar/SIMD conversion, decoding, playback and CIA creation succeeded. The final `scripts/verify-live-web.mjs after` uses the same profile to test the normal worker update lifecycle, updated cache, real scalar/SIMD conversions, downloads, full independent native decoding, player startup, two-episode CIA creation/verification and offline conversion. The offline phase relaunches that persistent profile through an unreachable local proxy: a never-cached network probe must fail while cached conversion still works. This is stronger than the browser automation offline flag, which did not reliably block service-worker network requests in this environment. Test usage statistics are opted out. Test videos, templates, CIA outputs and screenshots remain outside Git. The managed network's TLS inspection requires a browser-only test certificate bypass; this does not alter site code or claim to validate its certificate chain.

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

- Official Playwright Firefox installed, but headless startup timed out with sandbox UID-map and software framebuffer failures. No Firefox execution pass is claimed.
- Real physical iPhone Safari memory pressure, backgrounding, eviction and installed PWA behavior remain untested. Linux WebKit is useful coverage, not an iPhone substitute. Browser storage quotas can prevent saving large outputs; downloads remain available when optional persistence fails.
- CIA packaging requires a locally supplied compatible legally obtained player template; none is distributed. Existing Azahar playback evidence remains valid; no new emulator or physical 3DS playback claim is made for this cache-only release.
- Indexed seeking requires supported validated indexes and safe intra starts/pairs; unsupported files retain forward decoding. Scene-aware allocation improves automatic use of the cap on the measured fixture, but matched-actual-byte quality tied a manually retuned uniform baseline. See `INDEXED_SEEK_COMPRESSION.md`.
- Old offline tabs keep their existing active worker until all tabs for the app close; the prepared update then activates. No user movie data is deleted to force an update.
- Locally refreshed desktop archives are not republished by this web release; native macOS execution remains unverified.

Final local release rerun: **48 Chromium passed in one clean run, zero failures/skips**, including real engine URL-tag assertions. Final Node rerun: **361 passed, zero skipped**. Final WebKit: **five passed**, plus the extra editor/export recheck. All 52 offline assets, root/deployment parity, engine-release tags and provenance pass the current-source gate.

## Final published result

Application commit **`479d65567c56592d33d648e79d78c86b73d825f6`** was pushed directly to `master`; Pages reports **built**. The public site was then checked at **2026-11-18 18:27–18:28 UTC**. All **52** deployed manifest assets matched local SHA-256 values; the offline manifest and service worker matched, and both WASM engines had the correct MIME type.

The same persistent profile migrated from the previously saved release through the intermediate cache to **20261118t**, leaving only the final scoped cache. Both live scalar and SIMD conversions downloaded valid MOFLEX files and passed independent native full decoding. Live playback started. The live CIA editor produced a **2,574,080-byte, two-episode CIA** with title ID **000400000C456700**, independently verified by the native verifier. VidInjector extraction confirmed both original 400×240 MOFLEX payloads byte-for-byte. An independent CIA/NCCH/ExeFS parse confirmed the embedded `.code` player is byte-identical to the supplied template executable; hashes and sizes are in `WEB_RELEASE_20261118_VALIDATION.json`.

The persistent profile then restarted with an unreachable network proxy: a never-cached request failed, while the cached app reloaded with cross-origin isolation, completed a real conversion, and opened the CIA editor. This verifies offline execution rather than only successful cache installation. **106 observed engine requests used the expected release tag**. Screenshots and synthetic media remain outside Git. No new physical-device or Azahar playback claim is made.

The follow-up documentation commit changes no application asset or offline version; its application content is exactly the release tested above.
