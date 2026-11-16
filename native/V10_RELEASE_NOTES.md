# MobiPEG V10 MotionDetail — significant measured quality improvement

**Experimental release, November 16, 2026. Physical Old 3DS hardware
playback verification remains outstanding for this specific V10 output.**

V10 preserves real motion vectors in blocks that V9 could incorrectly force
to zero, then uses the saved bitrate to choose more accurate quantizers.
The goal remains a Nintendo-sized, stereoscopic MOFLEX with better fine detail
and fewer visual glitches on fast cuts.

## Full Avatar 3D trailer — matched source, matched budget

All comparisons use the same 4,826 alternating stereo eye frames (2,413
left/right pairs), at 400x224 YUV420p, and the same independently decoded
audit method. The Nintendo video is a **size/reference example**; mismatched
preprocessing, color and timing prevent direct interpretation of its PSNR.

| Metric | V9 TextureGuard | V10 MotionDetail | Difference |
|---|---:|---:|---:|
| Final MOFLEX file bytes | 20,553,728 | **20,529,152** | **-24,576 bytes** |
| Official Nintendo file bytes | 20,588,544 | **20,588,544** | V10 **-59,392 bytes** |
| Video payload bytes | 15,778,797 | **15,764,339** | **-14,458 bytes** |
| Luma PSNR (dB) | 34.90185 | **35.55915** | **+0.65730 dB** |
| Same-method sampled SSIM | 0.935675 | **0.944206** | **+0.008531** |
| Source-edge mean-square error | 76.498 | **66.214** | **-13.44%** |
| Error immediately after scene cuts | 25.173 | **21.962** | **-12.76%** |
| Static-region temporal error | 19.217 | **17.361** | **-9.66%** |
| High-frequency energy in source-flat areas | 0.768531 | **0.735352** | **-4.32%** |
| 5th-percentile frame PSNR (dB) | 31.2759 | **31.6692** | **+0.3933 dB** |
| Peak nonoverlapping 1-second video payload (kbps) | 2,889.040 | **2,782.552** | **-3.69%** |

**This is a much bigger improvement than V8 to V9**, although measured
fidelity is not a substitute for a blind subjective comparison on an Old 3DS.
The old encoder still has opportunities in motion compensation, in-loop
reconstruction, chroma treatment, real-time speed and rate-control spikes.

## Tests and safeguards

- **300 new V10 decoder-verified GOP candidate encodes**; all successfully
  encoded and decoded (six variants per section, 50 selected sections).
- **500 earlier V9 trials** retained for reference: 800 decoder-verified
  candidate trials across the two improvement passes, plus a 44-trial pilot
  and 12-test quantizer pilot in this V10 investigation.
- V10 chose 39 motion-preserving/finer-qx sections, five finer-qy sections,
  two further-fine-qy sections, one activity-protected section and three
  other motion-preserving sections.
- All 4,826 coded eye frames and all encoded ADPCM audio decoded with no
  errors. The decoded audio PCM SHA-256 is **identical to V9**.
- Exact video packet count and payload sums verified after final stereo mux.
- Independent per-second payload audit shows V10's peak below V9's.
- Native Linux patched FFmpeg/x264 compiled. macOS build source supplied but
  not run on a Mac in this investigation.

## Old 3DS check required

Play `Avatar_3D_MobiPEG_V10_MotionDetail.moflex` in **Nintendo 3D Movie
Viewer**. Check the stereo eye order, perceived resolution in the jungle and
underwater scenes, cuts, smooth playback, and audio sync. Report any new
temporal artifacts or stalls, since disabling forced zero-motion vectors
changes the 3DS decoder's motion-compensation workload.

Do not label the encoder production-ready or Nintendo-equivalent until
hardware playback and broader-source subjective comparisons confirm it.
