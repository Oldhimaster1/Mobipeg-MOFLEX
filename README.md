# MobiPEG long-movie preview downloads

Built locally, without a GitHub Actions dependency. Source and review:
[development branch](https://github.com/Oldhimaster1/Mobipeg-MOFLEX/tree/feature/long-movie-portable) · [PR #1](https://github.com/Oldhimaster1/Mobipeg-MOFLEX/pull/1).
The current master/Pages release is preserved.

| Download | Validation |
| --- | --- |
| [Windows x86-64](MobiPEG-windows-x86_64.zip?raw=true) | Native launcher and bundled Python/encoder tested under Wine: 2D, full-SBS, half-SBS, language selection, full decoding, paths with spaces, and file protection. GUI untested. |
| [Mac Apple Silicon](MobiPEG-macos-arm64.tar.gz?raw=true) | Cross-built; architecture, system imports and ARM64 ad-hoc signature hashes checked. Not run on macOS. |
| [Mac Intel](MobiPEG-macos-x86_64.tar.gz?raw=true) | Cross-built; architecture/system imports checked. Unsigned. Not run on macOS. |
| [Linux x86-64](MobiPEG-linux-x86_64.tar.gz?raw=true) | Native portable conversion/decode tests passed; built on Debian glibc 2.41. GUI untested. |
| [Web app + rebuilt scalar/SIMD WASM](MobiPEG-Web-WASM.zip?raw=true) | Both engines passed 2D/stereo encode/decode tests and real Chromium OPFS joining/download/cleanup tests. Includes local server instructions. |

Download the entire archive and extract it. Desktop packages include Python/Tk,
custom FFmpeg/ffprobe, licenses and corresponding project sources. Keep all
extracted files together. Open MobiPEGStudio.exe on Windows, or MobiPEGStudio on
Linux/Mac. No separate Python or FFmpeg installation is required. Packages are
not developer-signed/notarized. Matching `.sha256` files are alongside each archive.

Long browser mode uses bounded 30-second OPFS chapters and audio-block-aligned
joins. Synthetic joined timelines at 5/10/30/60/90/120/180 minutes passed full
video/audio decoding, exact frame counts, audio duration within 6 ms, and late
seeks. The three-hour output contains 259,200 frames. These are repeated synthetic
chapter tests, not diverse feature-film encodes.

Physical 3DS long-movie/stereo playback and seeking beyond the historical
71m35s duration field, iPhone Safari long-duration memory limits, and Mac GUI
execution remain unverified. No physical-device compatibility is claimed. All
user media processing stays local; no video is uploaded.

Additional regression checks: 261 JavaScript tests and 19 native tests passed. Both browser engines also handle audio extending beyond the video.
