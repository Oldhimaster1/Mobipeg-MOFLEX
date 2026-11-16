# MobiPEG V15 — Old3DS-oriented layout-0 stereo correction

Updated November 16, 2026. This corrects the packaging of **3D** video in `MobiPEG_Studio_V15.py`. It **does not** certify compatibility with real Old3DS/New3DS hardware; the user must test on the console.

## What was broken

The initial V15 Studio route cropped and independently processed each eye but then joined both eyes horizontally into a **single 800×224 packed SBS image** and wrote MOFLEX `ImageLayout=4`. That layout previously failed on a user's original 3DS. Its coded rate was 24 fps, not 48 eye frames per second. Merely changing `-mo_layout 4` to `0` without interleaving the actual coded frames would also be incorrect.

## Exact fix

For `--mode full-sbs` and `--mode half-sbs`:

1. Normalize at the requested **displayed** stereo rate, e.g. 24 stereo pairs/sec.
2. Split left/right; crop each half; independently scale, pad, and optionally filter each eye. Half-SBS's per-eye `setsar=2` correction is retained.
3. Assign left-eye timestamps `0,2,4,...` and right-eye timestamps `1,3,5,...` in a 48 Hz coded time base. The FFmpeg `interleave` filter emits left,right,left,right in sequence.
4. Encode **400×224 per coded eye** (by default) at **48 coded fps** for 24 displayed stereo fps. The full SBS source width is **not** retained in the encoded frame.
5. Use `-mo_layout 0 -mo_interleave_input_double_rate 1` in **both** the video encode and the ADPCM final remux. This writes the 24 Hz *display* descriptor while keeping 48 eye packets per second.
6. Use `coded_frames / 48` for real-time audio length (not `coded_frames / 24`). Ensure an even coded-frame count and detect the native demuxer's reported frame rate during remux: older versions expose displayed fps, so apply input `-itsscale 0.5`; corrected demuxers expose 48 coded fps and require no compensation. The remux output always explicitly advertises coded fps before writing the half-rate descriptor.
7. Correct the bundled FFmpeg's `libavformat/moflex.c` demuxer: for layout 0/1 use *twice* the descriptor rate as the coded packet time base. Leave layout 6 (2D) and packed modes unchanged. This fixes software-side reported duration, timestamp-based remuxing, and seek/decoding expectations.

## Verification performed

- **15/15 V15 Studio unit/integration tests passed** using the existing custom FFmpeg binary, including actual full-/half-SBS encode, left-eye red/right-eye blue alternation, 48 coded frames for one second of displayed stereo, ADPCM audio duration, and raw layout-0 descriptor byte tests.
- **2D output was bit-exact** against the archived initial V15 Studio version (identical SHA-256 on the same Sonic test video, quantizer, preset and encoder binary). The V15 2D code path is otherwise preserved.
- The native MOFLEX muxer flag already existed; the revised Studio actually supplies it at both encode and remux steps.
- A standalone color-eye MOFLEX and an independent stereo-reference file are supplied separately for testing.

The included source builds on Linux using `bash BUILD_FOR_LINUX.sh` and on other platforms with the source's existing build procedures. Python/Tkinter is required for the GUI. A custom patched FFmpeg binary, **not standard system FFmpeg**, is mandatory. Windows custom build and actual 3DS player compatibility are **not** verified by these host tests.

## Use

```
python3 MobiPEG_Studio_V15.py --gui
python3 MobiPEG_Studio_V15.py --input movie_full_sbs.mp4 --mode full-sbs --resolution 400x224 --fps 24
python3 MobiPEG_Studio_V15.py --input movie_half_sbs.mp4 --mode half-sbs --resolution 400x224 --fps 24
python3 -m unittest discover -s V15 -p test_studio.py -v
```

Use `--ffmpeg /path/to/patched/ffmpeg` if the binary is elsewhere. Both the old and rebuilt FFmpeg versions' audio-remux timestamp behavior are handled; rebuilding from this fixed full source is recommended.

## Still required before release

- Test actual output on **real Old3DS and New3DS**, checking stereoscopic separation, eye order, video pacing, music sync and playback to the end.
- Seek forward/backward around cuts and GOP boundaries on console. FFmpeg tests do not validate the Nintendo player.
- Re-encode a complete trailer with this corrected stereo route and verify size/quality. A previous packed-SBS V15 Avatar file **must not** be mistaken for this corrected layout-0 format.
