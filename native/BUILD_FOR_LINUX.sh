#!/usr/bin/env bash
# Build the bundled, patched MobiPEG sources without a system-wide install.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
if [[ "$(uname -s)" != "Linux" ]]; then
  echo 'This script builds the Linux version. On macOS use BUILD_FOR_MAC.command.'
  exit 1
fi
for tool in gcc make pkg-config awk tar; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing dependency: $tool (install your distribution's build tools / pkgconf)"
    exit 1
  }
done
if [[ ! -f "$ROOT/source/ffmpeg/libavformat/moflexenc.c" || ! -f "$ROOT/source/x264/x264.h" ]]; then
  echo 'Incomplete source tree; re-extract the full MobiPEG custom source ZIP.'
  exit 1
fi
PREFIX="$ROOT/local"
BUILDDIR="$ROOT/.build-linux"
JOBS="${MOBIPEG_BUILD_JOBS:-4}"
case "$JOBS" in ''|*[!0-9]*) echo 'Invalid MOBIPEG_BUILD_JOBS'; exit 1;; esac
if (( JOBS < 1 || JOBS > 32 )); then
  echo 'Choose 1-32 build jobs.'
  exit 1
fi
# Consume all diagnostic output; grep -q can close the pipe early and make a
# working encoder fail capability checks under pipefail.
if [[ -x "$PREFIX/bin/ffmpeg" && -x "$PREFIX/bin/ffprobe" && "${MOBIPEG_REBUILD:-0}" != "1" ]] &&
   "$PREFIX/bin/ffmpeg" -hide_banner -h muxer=moflex 2>&1 | grep -- '-mo_interleave_input_double_rate' >/dev/null; then
  echo 'Already built. Set MOBIPEG_REBUILD=1 to rebuild.'
  "$PREFIX/bin/ffmpeg" -hide_banner -encoders | grep mobiclip
  exit 0
fi
mkdir -p "$PREFIX" "$BUILDDIR/x264" "$BUILDDIR/ffmpeg"
cp -a "$ROOT/source/x264/." "$BUILDDIR/x264/"
cp -a "$ROOT/source/ffmpeg/." "$BUILDDIR/ffmpeg/"

echo 'Building custom x264 backend for this Linux CPU...'
cd "$BUILDDIR/x264"
./configure --prefix="$PREFIX" --enable-static --disable-cli \
  --disable-opencl --disable-asm --enable-pic \
  --extra-cflags='-O3 -ftree-vectorize'
# Some x264 configure revisions append a later -fno-tree-vectorize. Replace
# that generated build-only flag so the intended C vectorizer actually runs.
sed -i 's/-fno-tree-vectorize/-ftree-vectorize/g' config.mak
make -j "$JOBS"
make install

echo 'Building modified FFmpeg/MOFLEX encoder and ffprobe...'
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
cd "$BUILDDIR/ffmpeg"
./configure --prefix="$PREFIX" --enable-gpl --enable-libx264 \
  --disable-debug --disable-doc --disable-ffplay --disable-autodetect \
  --enable-static --disable-shared --disable-x86asm \
  --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib"
# Force final executables to relink against the freshly built static x264;
# Make alone does not track libx264.a as a dependency of the FFmpeg targets.
make -j "$JOBS" fftools/ffmpeg.o fftools/ffprobe.o
make -j "$JOBS" -W fftools/ffmpeg.o -W fftools/ffprobe.o ffmpeg ffprobe
make install
"$PREFIX/bin/ffmpeg" -hide_banner -encoders 2>/dev/null | grep mobiclip >/dev/null || {
  echo 'ERROR: Missing Mobiclip encoder'; exit 1;
}
"$PREFIX/bin/ffmpeg" -hide_banner -h muxer=moflex 2>&1 | grep -- '-mo_interleave_input_double_rate' >/dev/null || {
  echo 'ERROR: Missing incremental MOFLEX muxer'; exit 1;
}
echo "SUCCESS: $PREFIX/bin/ffmpeg"
echo 'Usage: bash encode_macos.sh 2d /path/to/video.mp4'
