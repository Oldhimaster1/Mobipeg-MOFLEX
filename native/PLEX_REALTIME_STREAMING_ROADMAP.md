# Goal: Plex -> custom MobiPEG -> Nintendo 3DS live video

**Prototype now available for server-side progressive encoding; 3DS live playback is NOT complete.** This source package includes our new `-mo_live 1` encoder option and `tools/plex_live_bridge.py`, alongside normal `.moflex` file conversion. No actual Nintendo 3DS hardware or Mac build has validated live playback yet.

## Proposed streaming path

```text
Plex Media Server (authorized media + stream URL)
    -> local decoder / fps + geometry + TV-range conversion
    -> native patched x264/MobiClip (target: 400x240 ~30 fps)
    -> incremental MOFLEX muxer (-mo_live 1) [IMPLEMENTED, Linux verified]
    -> HTTP/1.1 chunked response + OS pipe backpressure [IMPLEMENTED, Linux verified]
    -> custom Nintendo 3DS live client + playback buffers [NOT IMPLEMENTED]
    -> MobiClip display/audio decode
```

Plex can supply the source video, but a normal Plex transcode (HLS/H.264) is **not a MOFLEX stream**. A custom intermediate service and a player path that actually consumes MobiClip on the 3DS are required. Never hardcode a Plex account token in scripts or a public archive; request the token at runtime and keep it off URLs/logs where practical.

## Resolved encoder blocker: MOFLEX now emits progressively

See `source/ffmpeg/libavformat/moflexenc.c` and `tools/plex_live_bridge.py`. The usual `-mo_live 0` muxer still buffers the entire movie to write the seek table at its front. The **new** `-mo_live 1` mode:

- Writes MOFLEX blocks to the output file/pipe **during encoding**, rather than keeping the whole compressed video in a buffer.
- Interleaves audio and video with a small lookahead, writes 2D and full-/half-SBS layouts, and flushes the output as encoded frames arrive.
- Removes the front seek table (which fundamentally requires knowing the future file layout). The output decodes with our FFmpeg and the Clownsec MOFLEX demuxer after completion; an actual 3DS needs a **live, forward-only player** and cannot use its current seek-oriented file reader.
- Keeps packet buffering bounded during normal continuous video+audio. A long live stream with prematurely ended audio may still cause queue growth, so an explicit memory limit or audio-end tracking is needed before an unattended server release.

## Clownsec Big Top integration — what the actual source does

Project: https://github.com/brainphreak/clownsec-bigtop (server) and https://github.com/brainphreak/clownsec-moflex-player (3DS homebrew). The server serves **completed** `.moflex` files through `http.ServeContent`; it does not encode new MOFLEX on the fly. Its 3DS side implements `FILE*` over HTTP byte ranges in `net/httpfile.c`. That implementation sends HEAD, requires a known `Content-Length`, and performs Range requests. The MOFLEX demuxer `decoder/moflex_demux.c:mfx_open_window` seeks to the **end of the file** and probes the last 2 MB to determine duration before rewinding. This blocks on an open-ended, unknown-length live stream.

The player also already includes `net/httpstream.c`, an HTTP-body -> ring-buffer worker used for other media. A correct Big Top live integration can reuse that transport but must expose a **new forward-only MOFLEX demux path** (no end-of-file probe or seeking), a buffered read strategy, and a way to start playback without `HEAD`/Range. Do not silently send our live endpoint to the existing `httpfile_open` function; it will fail.

Server side today: run `START_PLEX_LIVE.command` or directly `python3 tools/plex_live_bridge.py --rating-key 1234 --ffmpeg local/bin/ffmpeg`, after setting `PLEX_TOKEN`. Plex metadata `/library/metadata/<ratingKey>` is used to choose a `Part` URL; only your server receives the `X-Plex-Token` header. Local `--source` MP4/MOV/MKV also works. HTTP endpoint `GET /live.moflex` sends chunked raw MOFLEX; `GET /health` describes capability, explicitly indicating it is not compatible with the legacy Big Top client.

### Minimum homebrew live-player change set

1. Add a UI entry to select a live URL (or negotiate it from a Big Top/Plex item) and use `hs_open()` rather than `httpfile_open()`.
2. Add a forward-only demux stream reader. It must not call `fseeko(...,SEEK_END)`, estimate a file length, or probe the last megabytes. Preserve the first MOFLEX sync header for initial stream discovery and handle partial network reads without treating an empty *nonfinished* buffer as EOF.
3. Feed complete MobiClip frames into its existing decoder and interleaved ADPCM into its audio queue. Add a real-time pacing and buffering policy (e.g. 0.5–2 seconds initial buffer), cancellation, stall/reconnect semantics, and timestamp-based A/V sync.
4. Disable seeking/duration UI on live sessions, handle 3D side-by-side layout and old-vs-new console capabilities, and test on both an Old 3DS and a New 3DS.
5. If adding this to Big Top server instead of running this Python service separately, proxy an ongoing encoder process as an HTTP chunked response; do not buffer the entire response or fake a `Content-Length`.

## Speed requirement

At 30000/1001 FPS, sustained processing must be **at least 29.97 frames per wall-clock second**, ideally with headroom for source decoding, audio, network backpressure, and occasional hard frames. Throughput averaged over easy synthetic test frames is insufficient: include busy/hard scenes and seconds-long worst-case windows. The previously measured 5.87 FPS on a 2017 i7-7700HQ was **not** realtime. The custom Mac FPS is not yet measured.

The included `REALTIME_30FPS_CHECK.command` encodes 300 generated frames on your actual Mac and reports measured throughput. Then time normal clips with `ENCODE_2D.command`. Experimental independent 4-worker encoding may improve throughput, but has segment startup latency and potential GOP seam differences; it does not make this muxer progressive.

## Release milestones

1. **Measure:** Verify native Apple Silicon/Intel builds, full decode, encode FPS over 10+ varied real clips, RSS memory and file growth; record both aggregate FPS and worst consecutive 1-second window.
2. **Plex adapter:** Support Plex authorized direct stream over LAN/HTTPS (or server-side transcoding to a compatible intermediate). Keep direct-play selection and token handling separate from our encoder.
3. **Incremental MOFLEX protocol:** Implemented and checked against FFmpeg/Clownsec software demuxers for completed streams. Still need streaming-client handling, memory limits, reconnect boundaries and initial buffering.
4. **3DS client:** Build or adapt a dedicated homebrew receiver/buffer/player; test Old 3DS and New 3DS latency, frame continuity, audio, stereoscopic support and sustained Wi-Fi bandwidth.
5. **Load & failure tests:** Verify 30/60-minute sessions, fast scene changes, bitrate limits, dropped network packets, cancellation, Plex authentication expiry, reconnection, A/V sync and fallback quality.

**Now included:** Plex source resolver, streaming HTTP transport, source, test tools, and a Linux-verified experimental incremental muxer. **Not included/completed:** installable live-ready 3DS application, verified sustained 30 FPS on the user's CPU, Mac-compiled binary, reconnect/resume, and hardware playback.
