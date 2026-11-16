# MobiPEG experimental live Plex/MOFLEX — host engineering validation

Date: 2026-11-15. Target: developer preview, **not a hardware-verified 3DS release**.

## Result summary

- Built a new `-mo_live 1` option into the native custom MobiPEG FFmpeg muxer. It writes MOFLEX blocks progressively to a file, stdout pipe or HTTP bridge, without holding the complete encoded movie until `moflex_write_trailer()`.
- Confirmed **nonzero output before a real-time paced encode finishes**: 428,741 bytes were already written while the five-second progressive video source was running.
- Verified stdin/stdout **encoder-to-decoder piping** with video + ADPCM and no intermediate completed file.
- Encoded 2D and 3D side-by-side layouts. `ffprobe` recognized **800×240, 30 video frames and 37 audio chunks** in a one-second full-SBS HTTP stream. The FFmpeg decoder accepted the resulting file.
- HTTP `GET /health` returned capability JSON; `GET /live.moflex` completed as **HTTP 200 with chunked transfer**, and its downloaded output decoded. A nonexistent/nonmedia encoder input correctly returned HTTP **502**, not a misleading successful response.
- Tested a **mock Plex server end-to-end**: authenticated metadata lookup (`/library/metadata/1234`), protected MP4 HTTP part fetch with byte ranges, on-the-fly MOFLEX conversion over our bridge, and complete video decoding. No actual Plex account or user token was accessed.
- Verified the **actual Clownsec MOFLEX demuxer** from `brainphreak/clownsec-moflex-player` read both indexed and finished live-file variants. An experimental Clownsec forward-only demuxer patch then consumed live encoded MOFLEX **directly from a pipe before the producer finished**, parsing **60 video + 75 audio packets**, status 0.

## 200-case source-preserving equivalence suite

`tools/stress_live_moflex.py` independently encoded both the experimental live and original front-indexed MOFLEX outputs, decoded all video frames and (when present) audio PCM, and verified exact SHA-256 agreement of their raw decoded bytes.

| Variable | Coverage |
|:--|:--|
| Cases | **200 passed / 200 total**, no failures |
| Inputs | **5 source videos**: four distinct real uploads plus one generated A/V sample |
| Layout | 64 2D, 60 full-SBS, 76 half-SBS cases |
| Target rate | 46 × 10fps; 51 × 15fps; 53 × 24fps; 50 × 30000/1001fps |
| Video QP | 12, 16, 20, 24, 30 |
| Audio option | 90 cases requested audio; absent source audio was treated as optional |
| Clip duration | 0.25, 0.4, 0.8 and 1.2 seconds |
| Host run time | **169.83 seconds** for the complete 200-case suite; this is **not** a 3DS host real-time FPS measurement |

Every **live output** also passed the separately compiled Clownsec *seekable* demuxer packet-check program. The exact trial settings, per-case outcome and decoded-byte counts are in `LIVE_STRESS_200_RESULTS.json`. A separate 13-test Python suite passed for Plex source parsing, option construction and stereo layout; the mock Plex HTTP test passed separately.

### Existing-file compatibility regression

The new muxer with **`-mo_live 0` (default)** produced exactly the same finished `.moflex` bytes as the previous native Linux encoder for the 60-frame synthetic video fixture: both file SHA-256 hashes were

`a54bffea642ba17c18b08d1ca92860162cf7a3098aec924c06f339198a966a18`.

For the 60-frame A/V fixture, live and normal outputs decoded to **identical full video-frame bytes** and **identical concatenated raw 44.1kHz stereo PCM bytes**. Per-packet ADPCM boundaries were different (75 vs 60 audio packet groups), as expected from progressive flushing, but decoded audio bytes matched; further on-device sound/clock testing remains necessary.

## Clownsec live receiver building block

`tools/clownsec_forward_only_moflex.patch` is a patch against the **independently maintained** [`brainphreak/clownsec-moflex-player`](https://github.com/brainphreak/clownsec-moflex-player) code. It adds `mfx_open_live(FILE*)`, avoids probing the file tail, reads 4096-byte chunks from nonseekable streams, and explicitly disables seeking/pre-scan in live mode. It passed a native Linux pipe test; it has **not** been compiled using devkitARM or wired into the 3DS menu/playback/network code. No Clownsec upstream project was modified remotely.

## Still blocking end-to-end Old 3DS playback

1. **3DS client protocol:** The released Big Top player still calls `httpfile_open` using HEAD/Range. It must select an independent *live* mode that uses `net/httpstream.c`, a blocking/stream-aware `FILE*` wrapper, and `mfx_open_live` rather than the seek-oriented `mfx_open`.
2. **Rendering and sound:** Wire the incremental packets into the real 3DS decoder/audio queues with buffering, real-time pacing, and clean end/error/cancel handling. Validate 2D and SBS eye mapping on actual consoles.
3. **Sustained encoder throughput:** Previous Windows i7-7700HQ measurement was 5.87 FPS (four workers, QP12/subme9). That is well below 29.97 FPS, so the original Windows CPU cannot yet generate full-quality 30fps MobiClip in real time. Lowering output FPS reduces temporal fidelity and is an explicit tradeoff; it cannot be described as quality-preserving.
4. **Live edge cases:** Existing stream mode has no index or seek/reconnect support, no automatic adaptive mode, and no enforced maximum interleave queue when the audio ends early. Load test lengthy inputs, audio shorter than video, Plex token expiry, connection drop, network jitter and memory use.
5. **Mac/hardware validation:** The Mac source-build was prepared but **not built on macOS** in this environment; 3DS native playback was **not verified**. This test host's CPU is not comparable to the user's Windows i7.

These findings establish a functioning **host-side real-time MOFLEX transport prototype**, not a fully functioning Plex-to-Old3DS product.
