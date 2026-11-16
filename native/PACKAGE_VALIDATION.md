# Package verification notes (2026-11-15)

Package type: **macOS source-build developer preview** for the custom MobiPEG encoder.

## Confirmed in the Linux research environment

- The FFmpeg tree is extracted from the user's earlier MobiPEG source snapshot and **our** `moflex_seek_integrity_experimental.patch` is applied. The patch was successfully reverse-dry-run checked against the included `libavformat/moflex.c`, establishing that it is present.
- The modified x264 tree matches the source from our speed/quality research. There are no x86_64 Linux object files or native prebuilt binaries in the package.
- All five `.command` wrappers and the main Bash script passed `bash -n` shell syntax verification.
- The scene-aware Python multicore source passed `python3 -m py_compile` and gained color-range-aware normalization.
- A real synthetic **2D, 60-frame, QP12** conversion with AAC input audio produced MOFLEX ADPCM output, passed strict full-video and full-audio decode, and maintained all 60 packets.
- A real synthetic **full-SBS 3D, 60-frame, QP12** conversion with audio produced layout=4 output, passed strict full-video and full-audio decode, and maintained all 60 packets.
- The bundled scene-aware multicore Python tool completed a **60-frame** video+audio smoke test, verified the layout=6 header, matched the joined and remuxed compressed video packet hashes, and decoded its full output.
- The prior independent **418-case reliability** research report is included, clearly labeled as earlier Linux testing; it is not the number of test cases executed with this Mac ZIP.

## Still to be verified on the friend's Mac

- Apple Silicon and Intel cross-architecture **compilation and runtime**, including installed Xcode/Clang and pkgconf versions.
- Native Mac throughput, quality regression, full end-to-end 3D conversion, scene-aware multicore throughput and frame-seam behavior.
- Real hardware 3DS 2D/3D playback, stereo slider, long-file seeking, sound continuity, and audio tail.

**A failed build should be reported**, not replaced by the official upstream Mac binary: the official release is not equivalent to this custom source build.
