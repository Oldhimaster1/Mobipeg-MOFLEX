# MobiPEG V8 TextureGuard — experimental release candidate

## Main result (November 15, 2026)

V8 was built **without Nintendo's codec DLLs** and uses MobiPEG's native MobiClip bitstream encoder and stereoscopic MOFLEX muxer. The Avatar test file is a hardware **test candidate**, not yet confirmed on the Old 3DS.

| Output / measurement | Nintendo official | MobiPEG V7 | MobiPEG V8 |
|---|---:|---:|---:|
| Complete Avatar MOFLEX bytes | 20,588,544 | 20,578,304 | **20,570,112** |
| Video payload bytes | 15,926,292 | 15,810,029 | **15,797,387** |
| Total coded eye frames | 4,826 | 4,826 | **4,826** |
| Key / intra frames | 44 | 165 | **118** |
| Highest 1-second video bitrate | 1,979 kbps | 2,951 kbps | **2,897 kbps** |
| Full-frame luma PSNR vs the *same MobiPEG-normalized source* | 28.520 dB* | 34.735 dB | **34.895 dB** |
| SSIM including both eyes and additional scene-cut samples | 0.942974* | 0.934119 | **0.935719** |
| Source-edge luma MSE | 362.30* | 79.35 | **76.87** |
| Post-scene-cut luma MSE | 74.87* | 26.144 | **25.246** |
| Fifth-percentile eye-frame PSNR | 22.425 dB* | 31.226 dB | **31.259 dB** |
| Complete video and ADPCM software decode | Yes | Yes | **Yes** |

\* **IMPORTANT:** Nintendo used a different source preprocessing/scaling/color pipeline. Its file is not directly equivalent to the MobiPEG-normalized input. Also, several Nintendo frames near scene cuts are temporally offset compared with our normalized source. It is **invalid** to conclude that Nintendo is worse from the PSNR results, or that MobiPEG now equals Nintendo perceptually. The remaining SSIM gap matters, and visual/Old 3DS tests are decisive.

## Changes

1. Measured an expanded bank of quality candidates, specifically x264-derived MobiClip psychovisual settings, UMH motion search, and combinations, using **the unchanged MobiClip format**.
2. Rejected three trial outputs that didn't fully decode their expected frame count. Test failures are not included in the selection.
3. Unified 2-second and selected 4-second GOP candidates in a video-byte-budgeted allocator (the Avatar benchmark selects one 4-second chunk). This reduced intra frames from 165 to 118, but hardware seeking has not been tested for V8.
4. Chose a global stereo-aware quality allocation that improves *all five measured classes* relative to V7: PSNR, SSIM, edge MSE, worst-frame error, and post-cut error.
5. Protected the unchanged 400×224 per-eye, left/right alternating layout 0 and 24 FPS per eye, with bit-exact decoded audio matching V7 (SHA-256: `14a5a360faaac1acc880db8bed1f73e4ce1c4b073212b86f34c`).

## Cross-platform source and invocation

The entire MobiPEG V7 custom FFmpeg/x264 source is included unchanged. V8 extends the quality controller in `V8/adaptive_stereo_v8.py` and `V8/encode_stereo_v8.py`; it does not alter the compatible MOFLEX bitstream syntax.

1. Build the custom FFmpeg encoder using `BUILD_FOR_LINUX.sh` or `BUILD_FOR_MAC.command` in the package. You also need an installed system FFmpeg for source preprocessing and output verification.
2. Install Python dependencies: `python3 -m pip install numpy scikit-image`.
3. Encode an HSBS/FSBS source as stereoscopic 3D:

```sh
python3 V8/encode_stereo_v8.py input_HSBS.mp4 \
  --encoder local/bin/ffmpeg --probe local/bin/ffprobe \
  --video-kbps 1266.5 --workers 4
```

For Windows, use `py -3` and actual paths to your custom FFmpeg/ffprobe binaries (the Linux/Mac build scripts do not manufacture Windows builds). The V8 **portable** quality runner uses the already validated V7-safe 2-second GOP segmentation. The included Avatar V8 artifact uses one additional experimental 4-second GOP selected by the separate research knapsack; for bit-identical replication, consult the research scripts and candidate selection file. Do **not** claim portable V8 generates byte-identical files to this artifact without that step.

## Required release gates

- Verify V8 on **original 3DS hardware in Nintendo's 3D Movie Viewer** for complete playback, stereo depth, audio sync, seeking, and scene changes.
- Check scene/bitrate spikes and longer videos. V8's maximum video bitrate is still much higher than Nintendo's on the same trailer (2.90 vs 1.98 Mbps), which could matter on the Old 3DS.
- Cross-platform build tests and license audit; the shipped source is experimental and not a signed Windows/Mac app.
- Further controlled source preprocessing/color alignment and perceptual evaluation. Equal file size is **not** equal visual quality.

## Experimental test evidence

The research pack contains the exact software output and comparative data. Counts: 201 valid additional V8 GOP-mode trials (three candidate modes were rejected for incomplete decoding), 68 valid four-second GOP candidates, 27 standalone codec/speed comparisons, plus previous V7's 570 validated candidates. These are not independent 3DS hardware tests.

## Follow-up artifact/noise investigation (additional experiments)

Further checked **40 lambda-offset tests, 18 deblocking-option tests, and 18 gentle edge-aware prefilter trials** on representative Avatar segments. The experiments reinforce that a promising encoder switch must beat the reference using actual decoded output, not just a smaller file:

- Standard `-deblock` settings gave **byte-identical files** in these tests. They do not provide a demonstrated cure for MobiPEG's reconstructed block/grain artifacts in the tested MobiClip path.
- Light spatial preprocessing could reduce flat-region small-scale residual, but **lost SSIM and fine detail** in the tested material; it was therefore rejected for the production default. This intentionally preserves the user's requirement not to remove grain by indiscriminately blurring texture.
- A 404-eye-frame source-flat-region audit measured small-scale reconstructed luma energy of **0.5521** (source), **0.5514** (Nintendo), **0.7789** (V7), and **0.7654** (V8). Lower is not automatically superior: this proxy can combine ringing, grain, and legitimate fine texture. Nevertheless the remaining ~39% V8 excess against Nintendo in source-flat areas is a concrete difference worth deeper investigation.
- Across tested short scenes, changing candidate lambda offsets provided limited additional Pareto improvements but **did not justify replacing the fully validated V8 bitstream** under the matched-size, all-metrics release criterion.

New machine-readable tests are under the result ZIP's `lambda_expanded/`, `deblock/`, `prefilter/` folders. The chart `Flat_Region_Grain_Proxy.png` illustrates the unresolved grain/ringing metric. **Nintendo-level perceptual parity has not been demonstrated.**
