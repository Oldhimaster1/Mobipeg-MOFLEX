#!/usr/bin/env bash
# Run in an MSYS2 MINGW64 shell with mingw-w64-x86_64-gcc,
# mingw-w64-x86_64-pkgconf, make, diffutils and perl installed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
[[ "${MSYSTEM:-}" == MINGW64 ]] || { echo 'Use the MSYS2 MINGW64 shell.'; exit 1; }
for tool in gcc make pkg-config awk tar diff perl; do
  command -v "$tool" >/dev/null || { echo "Missing build tool: $tool"; exit 1; }
done
PREFIX="$ROOT/local"
BUILDDIR="$ROOT/.build-windows"
JOBS="${MOBIPEG_BUILD_JOBS:-4}"
[[ "$JOBS" =~ ^[0-9]+$ ]] && (( JOBS >= 1 && JOBS <= 32 )) || { echo 'Use 1-32 build jobs.'; exit 1; }
if [[ -x "$PREFIX/bin/ffmpeg.exe" && -x "$PREFIX/bin/ffprobe.exe" && "${MOBIPEG_REBUILD:-0}" != 1 ]] &&
  "$PREFIX/bin/ffmpeg.exe" -hide_banner -h muxer=moflex 2>&1 | grep -q -- '-mo_interleave_input_double_rate'; then
  echo 'Already built. Set MOBIPEG_REBUILD=1 to rebuild.'
  exit 0
fi
mkdir -p "$PREFIX" "$BUILDDIR/x264" "$BUILDDIR/ffmpeg"
cp -a "$ROOT/source/x264/." "$BUILDDIR/x264/"
cp -a "$ROOT/source/ffmpeg/." "$BUILDDIR/ffmpeg/"
cd "$BUILDDIR/x264"
./configure --prefix="$PREFIX" --host=x86_64-w64-mingw32 \
  --enable-static --disable-cli --disable-opencl --disable-asm \
  --extra-cflags='-O3 -ftree-vectorize'
sed -i 's/-fno-tree-vectorize/-ftree-vectorize/g' config.mak
make -j "$JOBS"
make install
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
cd "$BUILDDIR/ffmpeg"
./configure --prefix="$PREFIX" --target-os=mingw32 --arch=x86_64 \
  --enable-gpl --enable-libx264 --disable-debug --disable-doc --disable-ffplay \
  --disable-autodetect --enable-static --disable-shared --disable-x86asm \
  --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib -static-libgcc"
make -j "$JOBS" fftools/ffmpeg.o fftools/ffprobe.o
make -j "$JOBS" -W fftools/ffmpeg.o -W fftools/ffprobe.o ffmpeg.exe ffprobe.exe
make install
"$PREFIX/bin/ffmpeg.exe" -hide_banner -encoders 2>/dev/null | grep -q mobiclip
"$PREFIX/bin/ffmpeg.exe" -hide_banner -h muxer=moflex 2>&1 | grep -q -- '-mo_interleave_input_double_rate'
echo "SUCCESS: $PREFIX/bin/ffmpeg.exe"
