# Azahar CIA runtime validation

The release gate for this milestone is successful Azahar testing, as accepted by the user. Physical Nintendo 3DS compatibility remains unverified.

The official Azahar 2126.2 AppImage was downloaded from the azahar-emu GitHub release. Its SHA-256 was `af037f8b775198f636b14bcfe63fb401b02246ebfefe1025bb905ce042556960`. Testing used Linux, Xvfb at 1280×720, Xfwm4 in a D-Bus session, Mesa llvmpipe OpenGL and HLE DSP. A local PulseAudio null sink supplied a monitor for actual emulator audio capture. No emulator, firmware, player executable, template or generated CIA is distributed in this repository.

## Runtime results

CIAs were generated through the actual Chromium CIA interface using a compatible local collection template. They were installed with Azahar's `--install` option and the installed `.app` was launched. Testing proceeded beyond installation and boot.

| Collection | Zero-based episodes played | Result |
|---|---|---|
| 2 | 0, 1 | Menu, advancing frames, distinct audio tones, seek, menu return, normal exit and relaunch passed |
| 5 | 0, 2, 4 | Correct selected titles, video, audio and menu returns passed |
| 10 | 0, 4, 9 | Correct selected titles, video, audio and menu returns passed |
| 20 | 0, 9, 19 | Correct selected titles, video, audio and menu returns passed |
| 27 | 0, 13, 26 | Correct selected titles, video, audio and menu returns passed |

The synthetic 2D fixtures have red/blue backgrounds, white flashes and 440/880 Hz audio pulses. They use 400×240, 24 fps and ADPCM. Captured audio showed the expected tones, and screenshots showed advancing on-screen playheads and changing video frames. Short-clip flash/tone timing was checked from the capture. Capture scheduling and software rendering prevent a sample-accurate latency claim. This does not validate long-film synchronization or throughput.

The template's filmstrip thumbnails appeared correctly. Separate Chromium/native extraction regressions cover custom image thumbnails and banner assets. The last page of the 27-episode menu displayed episodes 24, 25 and 26, and episode 26 played successfully.

Early automated attempts missed controller events and one attempt selected episode 18 instead of 19. Those attempts were excluded. The corrected 20/27 runs read the highlighted selection before launch, and the actual player title was checked from screenshots. Initial setup and OCR failures are not counted as playback passes.

## Bugs fixed from runtime evidence

- The player menu retained the template's long title and publisher even when the SMDH was edited. The browser packager now updates those localized settingsTL fields alongside the title/save-data IDs.
- Left-first encoded alternating frames with layout 0 appeared with reversed eyes. With identical frames, layout 1 displayed the intended red left eye and blue right eye in Azahar's SideBySide mode, with swap-eyes disabled and 3D factor 100. Native and browser encoders now emit layout 1 for left-first alternating stereo. Player/export interpretation was corrected for layouts 0/1. Packed layouts 2–5 were not reinterpreted by this change. Stereo checkpoint identities now distinguish corrected ranges; 2D checkpoint identities are retained.
- The original 320×240 test fixture left an unfilled edge in this template player. The device fixture generator now emits 400×240 and the CIA editor recommends this tested geometry for other input sizes. Other sizes remain a compatibility limitation, rather than a claim of validated rendering.

A newly encoded layout-1 stereo fixture was byte-identical to the descriptor-corrected fixture tested in Azahar. The full-SBS source contained distinct red and blue eyes at 400×240 per eye. Both eye views were visible in the emulator. Physical stereoscopic viewing remains unverified.

## Reproduction

1. Download the official Azahar 2126.2 release. Extract the AppImage with `--appimage-extract` if FUSE is unavailable.
2. On a headless Linux host, provide Xvfb, a window manager such as Xfwm4 running under `dbus-run-session`, and software Mesa. A working window manager is needed for reliable Qt focus/input. Provide PulseAudio with a null sink and monitor if no physical audio device is available.
3. Generate fixtures with `python3 scripts/prepare-cia-device-test.py /path/to/new-directory` and run `node scripts/dev-server.mjs`.
4. Open the local CIA builder in Chromium. Supply the synthetic MOFLEX files and your compatible local collection-player template. Use distinct filenames and episode titles for larger collections. Build/download the actual CIA.
5. Run `azahar --install movie.cia`, then launch the installed application from the emulator UI or its installed `.app`. Wait for initial extra-data creation to finish before selecting episodes.
6. Play both test episodes, use the player Back button to return, seek, exit normally and relaunch. For larger collections, verify the selected title before playing first/middle/last entries. For stereo, enable SideBySide and 3D factor 100 with eye swapping disabled.
7. Capture screenshots and audio/video. Check the recording itself and the emulator logs before reporting a pass.

Runtime evidence is preserved in the workspace artifact `mobipeg-azahar-evidence.zip`, containing screenshots, recordings, timings and sanitized logs. It excludes CIAs and template/application binaries. The source fixtures and native-compatible project remain outside Git. Follow `CIA_DEVICE_TEST.md` for optional physical testing.

Large-file stress testing, Safari/iPhone behavior, other template implementations and physical 3DS installation remain separate unfinished verification areas. The existing portable archives are not rebuilt by this milestone; the changed source wrappers and web application use the corrected layout flag without requiring codec/WASM rebuilding.

## Final regressions

348 Node tests passed, along with 13 native tests and the additional SIMD FastAudio/MP4 test. Chromium passed 14 upgrade cases, 10 framing cases and five long-movie cases. The fixture-dependent scalar/SIMD cases were explicitly rerun with a generated 65-second two-track stereo fixture; both passed, including checkpoint reuse, selected Japanese-labeled audio, full decoding and cleanup. `azahar-validation.json` records the results and evidence checksum. Codec/WASM assets were unchanged, while their invoking modules, provenance and offline manifests were synchronized. The CIA page wording now describes actual local CIA creation.
