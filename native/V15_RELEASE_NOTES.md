# MobiPEG Studio V15 — verified engineering results (2026-11-16)

## What has changed

- `MobiPEG_Studio_V15.py`: a Python 3 graphical interface and CLI for encoding 2D, full-width SBS 3D, or half-width SBS 3D video to the native MOFLEX/Mobiclip format. Requires the *patched* custom FFmpeg build in this source bundle; stock FFmpeg cannot encode Mobiclip.
- `--motion-refinement auto`: enables an **existing, previously experimental native motion-vector refinement path** in the bundled x264/Mobiclip encoder for the `quality` and `best` profiles. This is a new production-path selection and safety wrapper, **not** a newly invented compression algorithm. `--motion-refinement off` gives the earlier control behavior.
- Selectable target format, FPS, per-eye resolution, presets, and optional cleanup filters. Spatial filtering is applied *separately* to the two eyes to avoid stereoscopic ghosting.
- Optional `--max-size-mb N` is a **hard cap on the finished MOFLEX**, with actual repeated encodes, including ADPCM and container padding. If the requested cap is impossible at supported quantizers, conversion fails without publishing an over-budget file. Encoding under a cap is slower.
- Checks the output by **fully decoding video and audio** before publishing the destination. Existing output files are preserved unless `--overwrite` is explicit. Input videos are never modified.

## Controlled 2D results: 15 diverse 5-second video samples

Same 24 fps, same Q30, source-normalized dimensions and decoding, same muxer; only the MV-refinement toggle changed. PSNR is *luma* PSNR versus a normalized source. Byte counts represent complete MOFLEX. See `V15_15_Samples_Summary.json` for each raw result.

| Content | V15 PSNR gain | MOFLEX bytes saved |
|---|---:|---:|
| Anime opening | +0.109 dB | 4.69% |
| Anime later scene | +0.057 dB | 4.40% |
| Anime ending | +0.015 dB | 1.48% |
| Bad Apple opening | +0.177 dB | 1.37% |
| Bad Apple later | +0.043 dB | 3.16% |
| Nature clip | +0.122 dB | 0.00% |
| Sonic animation | +0.030 dB | 6.52% |
| Climbing clip | +0.283 dB | 10.81% |
| Group clip | +0.314 dB | 11.94% |
| GameCube animation | +0.156 dB | 0.00% |
| Avatar 2D action | +0.046 dB | 11.39% |
| Avatar title | +0.337 dB | 0.00% |
| Yip opening | -0.00007 dB | 0.00% |
| Yip later | -0.003 dB | 1.37% |
| Yippee jazz | +0.005 dB | 2.70% |

Across the 15 individual samples: 13 positive PSNR results, 11 smaller files, mean PSNR +0.113 dB and mean relative byte reduction 3.99%. These are arithmetic means of per-sample differences, **not** a global whole-movie guarantee. The visible changes in still images can be subtle.

## Full videos with audio (not five-second excerpts)

| Real user video | Frame count | Control bytes | V15 bytes | Saved | Luma PSNR control → V15 |
|---|---:|---:|---:|---:|---:|
| Anime.mp4, 62.2 s normalized | 1,493 | 13,987,840 | 13,426,688 | 4.01% | 40.43049 → 40.51116 dB |
| Yip.mp4, 26.7 s normalized | 640 | 3,174,400 | 3,162,112 | 0.39% | 41.22341 → 41.22557 dB |

Both control and V15 outputs passed full-video and full-audio decoding; frame counts and decoded-audio PCM SHA-256 matched. `V15_FULL_VIDEO_AUDIT.json` includes per-frame MSE, dark-region fidelity, edge error, sampled SSIM, and checksums. The full input videos are not bundled; see the provided finished MOFLEX previews.

## Stereoscopic comparisons

20 actual **800 × 224** Mobiclip 3D trial files encoded across four Avatar excerpts and an independent two-eye parallax source, each fully decoded. The V15 trial improved or maintained reconstructed quality in the measured examples while frequently reducing bytes. Per-trial numeric details in `V15_STEREO_SWEEP.json`; side-by-side left/right comparisons are in `V15_Real_3D_Stereo_Comparisons.png`.

The **100-second** Avatar 3D experimental whole-video comparison is extremely close to V14 Safe:

| Encoder | Complete file | Full-video luma PSNR |
|---|---:|---:|
| V14 Safe/CutGuard | 20,570,112 bytes | 36.083328 dB |
| V15 motion-refine experiment | 20,586,496 bytes | 36.084564 dB |
| Nintendo reference | 20,588,544 bytes | separately compared visually |

V15 increases PSNR by only **+0.00124 dB** vs the already-optimized V14 Safe file, while costing 16,384 additional bytes. It is 2,048 bytes smaller than the Nintendo file. This is a microscopic objective gain and likely **not visually distinguishable**. Its decoded audio PCM SHA-256 matches the V14 baseline, and all 4,826 coded video frames decode. This experimental 3D file is a **GOP-constrained, stitched variant**, not produced by a single generic Studio command. A real 3DS hardware playback test is still required, especially at seek boundaries and scene cuts; do not market it as hardware-validated.

## Tests and honest negative results

- 90 spatial preprocessing trials (smoother filtering did *not* consistently improve PSNR and is **not** enabled by default).
- 135 adaptive-Q timeline trials.
- 225 native encoder parameter/motion-refinement sweeps.
- 20 real stereo MOFLEX trials.
- 25 scene-group RDO trials (the attempted per-scene Q adjustment gave no useful size/quality gain; retained original plan).
- 51 full Avatar GOP checks (one bit-identical baseline check plus 50 experiment candidates), with scene-cut and motion guards.
- **24 passed Python unit/integration tests** across V13 (5), V14 (6) and Studio V15 (13). V15 tests include live encoder invocation, hard filesize limits, 3D eye layout, audio, complete decode, source unchanged, overwrite protection, frame-rate/quantizer constraints.
- An additional **20 FFmpeg seek/decode smoke probes** at selected timestamps across the V15 full Avatar 3D experiment, full Anime, and full Yip; `V15_SEEK_DECODE_SMOKE.json` records per-probe hashes and results. Successful FFmpeg seeking **does not substitute for 3DS hardware seeking tests**.

The numeric counts include alternative trial encodes of the *same* content. They are **not** 546 separate full-length movies. Controlled tests demonstrate objective quality and file-size gains in the samples, not guaranteed subjective superiority to the proprietary Nintendo encoder across all video material. Real Nintendo 3DS hardware QA remains outstanding.

## Quick start

See `V15_STUDIO_QUICKSTART.md` for build requirements, GUI, CLI commands, hardware testing checklist, and comparison-file layout.
