#!/bin/bash
# Compiles OUR patched MobiPEG FFmpeg + x264 source on Intel or Apple Silicon.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer must run on macOS."
  exit 1
fi

echo "MobiPEG CUSTOM encoder — macOS build"
echo "This is the experimental custom source, NOT the stock upstream binary."
if ! xcode-select -p >/dev/null 2>&1 || ! xcrun --find clang >/dev/null 2>&1; then
  echo "Apple Command Line Tools are required. Run: xcode-select --install"
  exit 1
fi
if ! command -v pkg-config >/dev/null 2>&1; then
  echo "The pkg-config tool is required. If Homebrew is installed, run:"
  echo "    brew install pkgconf"
  echo "Homebrew: https://brew.sh"
  exit 1
fi
for tool in make awk tar; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing build tool: $tool"; exit 1; }
done

if [[ ! -f "$ROOT/source/ffmpeg/libavformat/moflex.c" || ! -f "$ROOT/source/x264/x264.h" ]]; then
  echo "The bundled custom source tree is incomplete. Please re-extract the ZIP."
  exit 1
fi

PREFIX="$ROOT/local"
BUILDDIR="$ROOT/.build"
mkdir -p "$PREFIX" "$BUILDDIR/x264" "$BUILDDIR/ffmpeg"
if [[ -x "$PREFIX/bin/ffmpeg" && -x "$PREFIX/bin/ffprobe" && "${MOBIPEG_REBUILD:-0}" != "1" ]] &&
   "$PREFIX/bin/ffmpeg" -hide_banner -h muxer=moflex 2>&1 | grep -q -- '-mo_interleave_input_double_rate'; then
  echo "Already built. Set MOBIPEG_REBUILD=1 to build again."
  "$PREFIX/bin/ffmpeg" -hide_banner -encoders | grep -i mobiclip || true
  exit 0
fi

# Build in private copies so the delivered source remains pristine.
echo "Copying patched x264 source..."
cp -R "$ROOT/source/x264/." "$BUILDDIR/x264/"
echo "Copying patched FFmpeg source..."
cp -R "$ROOT/source/ffmpeg/." "$BUILDDIR/ffmpeg/"
JOBS="${MOBIPEG_BUILD_JOBS:-4}"
case "$JOBS" in ''|*[!0-9]*) echo "Invalid MOBIPEG_BUILD_JOBS"; exit 1;; esac
if [[ "$JOBS" -lt 1 || "$JOBS" -gt 16 ]]; then echo "Use 1–16 build jobs"; exit 1; fi

echo "Building modified x264; C-only path, portable Apple Clang vectorization..."
cd "$BUILDDIR/x264"
CC="$(xcrun --find clang)" bash ./configure \
  --prefix="$PREFIX" --enable-static --disable-cli --disable-opencl \
  --disable-asm --enable-pic --extra-cflags='-O3 -fvectorize -fslp-vectorize'
# x264's configure can append a late '-fno-tree-vectorize', overriding the
# requested vectorizer. Edit only the generated build settings, not source.
if grep -q -- '-fno-tree-vectorize' config.mak; then
  perl -pi -e 's/-fno-tree-vectorize/-fvectorize/g' config.mak
fi
make -j "$JOBS"
make install

echo "Building modified MobiPEG FFmpeg / ffprobe with our seek + progressive muxer patches..."
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
cd "$BUILDDIR/ffmpeg"
CC="$(xcrun --find clang)" bash ./configure \
  --prefix="$PREFIX" --enable-gpl --enable-libx264 \
  --disable-debug --disable-doc --disable-ffplay \
  --enable-static --disable-shared --disable-autodetect --disable-x86asm \
  --extra-cflags="-I$PREFIX/include" \
  --extra-ldflags="-L$PREFIX/lib"
# A rebuilt libx264.a is external to FFmpeg's dependency graph. Force relink.
make -j "$JOBS" fftools/ffmpeg.o fftools/ffprobe.o
make -j "$JOBS" -W fftools/ffmpeg.o -W fftools/ffprobe.o ffmpeg ffprobe
make install

echo "Checking for the native MobiClip encoder and MOFLEX muxer..."
if ! "$PREFIX/bin/ffmpeg" -hide_banner -encoders 2>/dev/null | grep -q mobiclip; then
  echo "ERROR: The compiled ffmpeg has no mobiclip encoder."
  exit 1
fi
if ! "$PREFIX/bin/ffmpeg" -hide_banner -muxers 2>/dev/null | grep -q moflex; then
  echo "ERROR: The compiled ffmpeg has no moflex muxer."
  exit 1
fi
if ! "$PREFIX/bin/ffmpeg" -hide_banner -h muxer=moflex 2>&1 | grep -q -- '-mo_live'; then
  echo "ERROR: This build lacks our new -mo_live progressive streaming mode."
  exit 1
fi
echo "SUCCESS: Our custom encoder is now installed in: $PREFIX/bin"
echo "Next: Double-click ENCODE_2D.command, or run START_PLEX_LIVE.command for the HTTP preview."

# V5: verify the retail-compatible half-FPS stereo descriptor switch exists.
"$PREFIX/bin/ffmpeg" -hide_banner -h muxer=moflex 2>&1 | grep -q -- '-mo_interleave_input_double_rate' || { echo 'V5 stereo muxer option missing'; exit 1; }
