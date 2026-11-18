# Automatic VidInjector player validation — 2026-11-18

## Scope

MobiPEG browser release `20261118v` offers an explicit, optional route that obtains the collection player from the original VidInjector repository. The browser downloads only `files/base.cia`, `files/vector/multi.zip` and `arrays/bimgheader.bin` at revision `7eb44d5fb712cdd8a8a34981c2bfaefba8f29b64`. MobiPEG does not bundle, mirror or cache these third-party binaries in its repository or offline application cache.

The upstream repository has no license file discoverable at that revision. Technical compatibility therefore does not establish permission to use or redistribute its assets. The interface and documentation retain an explicit rights warning. A user-supplied compatible CIA remains supported and takes precedence when selected.

## Release-blocking failure and fix

The pull-request implementation initially passed its synthetic CIA, NCCH, RomFS, ExeFS and hash tests. A real Chromium build also passed the JavaScript inspector and independent Python content verifier. It nevertheless failed in Azahar immediately after starting the player executable, with a generic fatal error before the episode menu.

Comparison with the previously verified native VidInjector output found the missing player contract: multi-movie builds require the HOME Menu SMDH at both ExeFS `icon` and RomFS `/icon.icn`. VidInjector's source states that the RomFS copy is used while creating extra data and that the game crashes without it. The browser starter now supplies that file. Final packaging updates both copies together, including selected artwork and the edited application title/publisher.

The CIA inspector now validates more than the enclosing content and NCCH hashes. It checks every populated ExeFS directory entry for unique names, section bounds and its own stored SHA-256 digest. A usable `.code` must exist, be at least 4 KiB and contain nonzero executable data. Malformed-directory, corrupt-content, unsafe-ZIP and understated-expansion regressions remain covered.

The three downloads are checked against these exact release inputs before parsing:

| Resource | Bytes | SHA-256 |
|---|---:|---|
| `files/base.cia` | 197,056 | `f1edb172343232673f5a7b2fc7b22e2a1f802e07be513d4fce19e19dd5c1691f` |
| `files/vector/multi.zip` | 776,359 | `2522405ce6da3e2e76fa0e493790c41de56dcfca278b2af61319eda445546f08` |
| `arrays/bimgheader.bin` | 32 | `4fec9fc6183adfecd8fdbd8c9db9f5bd97f915e402f69f261862d800dd65fdb5` |

## Real browser and emulator result

The actual Chromium interface downloaded the pinned inputs and built a 2,574,592-byte CIA with title ID `000400000C432100`. Independent native verification checked its one content. VidInjector extraction matched both source MOFLEX SHA-256 digests exactly and showed byte-identical, valid SMDH files at ExeFS `icon.bin` and RomFS `icon.icn`.

Azahar 2126.2 installed the corrected CIA and launched the real player. On the first launch it created extra data and displayed two episode buttons. Episode one advanced through the red six-second 440 Hz fixture; episode two advanced through the blue six-second 880 Hz fixture. Both reached visible `00:03 / 00:06` playback states. The Back control returned to the two-entry menu. After terminating and reopening Azahar, the application opened directly to the collection rather than recreating extra data or showing a fatal error. A 28.004-second PulseAudio monitor capture was PCM16 stereo at 48 kHz, with -33.1 dB mean and -5.0 dB peak levels.

The emulator, player/template files, generated CIA, extracted binaries, screenshots, audio capture and MOFLEX fixtures are test artifacts outside Git. No physical Nintendo 3DS test is claimed.

## Automated checks

```sh
node --test tests/*.test.mjs
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/release.config.mjs
MOBIPEG_TEST_VIDINJECTOR_AUTO=1 \
MOBIPEG_TEST_CIA_MOVIES='["/path/episode-1.moflex","/path/episode-2.moflex"]' \
MOBIPEG_CIA_BACKEND=/path/to/VidInjector9002-CLI \
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers \
node tests/browser/node_modules/@playwright/test/cli.js test --config tests/browser/vidinjector-auto.config.mjs
node scripts/offline-assets.mjs
node scripts/validate-web-release.mjs
```

- Full Node: 371 passed; one optional local-native-template integration skipped in that unparameterized run.
- Clean Chromium release run: 30 passed; 20 large/local-fixture cases skipped. The six local-template collection cases were then run with real fixtures and passed at 1, 2, 5, 10, 20 and 27 entries. The automatic-player integration passed separately.
- Focused Linux WebKit: six passed, covering all eight interface languages, the Guide, SUPER editing/export, real offline conversion/playback, and scalar/SIMD conversion/playback.
- The scalar/SIMD engine binaries and codec sources did not change. Existing long-duration seek, segmentation and Azahar coverage from the preceding release remains applicable.

## Remaining limitations

- Physical Nintendo 3DS installation and playback are unverified.
- The upstream asset license/redistribution permission is unresolved. MobiPEG's opt-in original-source download does not resolve that legal question.
- The automatic route requires network access to the pinned GitHub revision. Offline CIA building still works with a compatible local template selected by the user.
- Linux WebKit automation is not physical iPhone Safari testing.

## Published-site verification

Application commit `a385ac6dec31957895729c0bb57a56257b6132ba` was fast-forwarded to `master`. GitHub Pages reported that exact commit built at `2026-11-18T23:14:08Z`. All 54 public manifest assets, the manifest, service worker and both WASM MIME types matched the local release.

The public CIA page then exercised the automatic-player control with the two test movies. It downloaded a 2,574,592-byte CIA with title ID `000400000C432100`; independent native verification checked its content, extraction matched both source movie digests, and the RomFS/ExeFS SMDH copies matched. The broader persistent-profile live check also passed scalar and SIMD conversion with full native decoding, player startup, local-template CIA generation, service-worker cache `20261118v`, and a real offline conversion after restarting behind an unreachable proxy. All 106 engine requests used the `20261118v` tag. The managed test network required a browser-only TLS-inspection bypass; direct Node HTTPS asset validation succeeded without modifying site code.

Machine-readable release facts are in `VIDINJECTOR_AUTO_PLAYER_20261118_VALIDATION.json`.
