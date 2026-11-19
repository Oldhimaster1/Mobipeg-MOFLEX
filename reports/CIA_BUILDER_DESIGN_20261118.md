# CIA Builder usability, live preview and artwork editor — 2026-11-18

## Implementation baseline

Based on master `12f1ec912158682383f6793944f8099713d16746`. All changes are isolated on `feature/cia-studio-preview-art-20261118` until full browser/runtime verification is available.

## Changes

- Three clear steps: choose movies, customize title/artwork, build CIA. The visible third-party VidInjector opt-in and licensing warning remain; manual local templates, project JSON, saved conversions, large collection splitting, banner audio and OPFS storage are retained in Advanced.
- Live 3DS-inspired preview shows selected icon/banner and ordered episode titles/thumbnails. Editing titles, image files, episode names or order refreshes immediately. The 3DS-style UI is a visual guide, **not an emulator rendering of the template's proprietary layout**.
- Local, cryptographically generated IDs in C0000–EFFFF; retries known IDs from this browser, warns on manually reusing a generated ID, and remembers IDs from successfully built parts. No site can reliably detect titles already installed on a 3DS.
- Artwork crop editor supports fill/fit, aspect framing presets, zoom, horizontal/vertical position and pointer dragging. It exports a 48×48 PNG for the HOME Menu icon and 200×120 PNGs for banner/episode imagery. Alternate aspect settings pad/clip within the expected output dimensions. These PNGs pass through the unchanged existing SMDH/BIMG/CBMD conversion path.
- Added responsive, keyboard-accessible controls and a touch-sized canvas; preserves original video files locally. Replaced artwork URL references are revoked to avoid accumulating browser memory. Safari BFCache restoration refreshes previews.
- Source and `dist/` copies, service-worker version `20261118w`, and both offline manifests updated; new JS and CSS added to offline caching.

## Tests performed here

- Executed all eight current `tests/cia-design.test.mjs` synchronous cases against the actual checked-in `cia-design.mjs` implementation using an isolated JavaScript/V8 harness with compatible assertion functions: **8 passed, 0 failed**. This is not a full Node test-suite run.
- Additional focused geometry, canvas clip and ID checks against actual source passed. Confirmed referenced DOM IDs exist in the CIA page, source/dist parity for new/edited CIA assets, CSS brace balance, and scripts without import syntax errors.
- Added Playwright coverage for ID generation and local collision warnings, artwork export sizes, real SMDH/BIMG converter integration, mobile overflow, episode title/order updates, and episode crop selection. Updated existing CIA packaging, VidInjector, offline and project tests to open the new Advanced section. **Playwright tests were added but were not executed in this environment**.

## Remaining verification before merge

Run in a full checkout with supported browser engines:

```sh
node --test tests/*.test.mjs
node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/release.config.mjs
node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/vidinjector-auto.config.mjs
node scripts/offline-assets.mjs
node scripts/validate-web-release.mjs
```

CIA packaging fixture tests require `MOBIPEG_TEST_CIA_TEMPLATE`, `MOBIPEG_TEST_CIA_MOVIES` and optionally `MOBIPEG_CIA_BACKEND`. The automatic-player browser integration requires `MOBIPEG_TEST_VIDINJECTOR_AUTO=1` and genuine input fixtures. Independently inspect extracted SMDH and episode textures, then test completed CIAs in Azahar and on real hardware. iPhone Safari/WebKit should be checked for editor file handling and memory.

**Not claimed:** successful full Node, Chromium, WebKit, hardware, or live website execution for this new branch. Master remains on its previously verified release until these checks pass. VidInjector rights remain unresolved.
