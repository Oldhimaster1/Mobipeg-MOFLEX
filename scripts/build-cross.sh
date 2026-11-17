#!/usr/bin/env bash
# Build native codec binaries locally on Linux. No GitHub Actions required.
# Needs Zig 0.14.1 and the LLVM archive tools shipped with Emscripten 4.0.10.
set -euo pipefail
TARGET="${1:?Usage: build-cross.sh macos-arm64|macos-x86_64|windows-x86_64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${ZIG:?Set ZIG to the Zig executable}"
: "${LLVM_TOOLS:?Set LLVM_TOOLS to a directory containing llvm-ar and llvm-ranlib}"
BASE="$ROOT/.build/cross/$TARGET"
PREFIX="$BASE/local"
mkdir -p "$BASE/x264" "$BASE/ffmpeg" "$PREFIX" "$BASE/tools"
case "$TARGET" in
 macos-arm64) TRIPLE=aarch64-macos.11.0; HOST=aarch64-apple-darwin; OS=darwin; ARCH=aarch64 ;;
 macos-x86_64) TRIPLE=x86_64-macos.11.0; HOST=x86_64-apple-darwin; OS=darwin; ARCH=x86_64 ;;
 windows-x86_64) TRIPLE=x86_64-windows-gnu; HOST=x86_64-w64-mingw32; OS=mingw32; ARCH=x86_64 ;;
 *) echo 'Unsupported target'; exit 1 ;;
esac
# Generated compiler wrapper is local to the ignored build directory.
python3 - "$ZIG" "$TRIPLE" "$BASE/tools/cc" <<'PYTHON'
import sys
from pathlib import Path
zig,triple,path=sys.argv[1:]
Path(path).write_text('#!/usr/bin/env python3\nimport os,sys\nzig='+repr(zig)+'\nos.execv(zig,[zig,"cc","-target",'+repr(triple)+',*[a for a in sys.argv[1:] if a not in ("-Wl,-dynamic,-search_paths_first","-Wl,--pic-executable,-e,mainCRTStartup")]])\n')
PYTHON
chmod +x "$BASE/tools/cc"
export ZIG_GLOBAL_CACHE_DIR="${ZIG_GLOBAL_CACHE_DIR:-$BASE/zig-cache}"
cp -a "$ROOT/native/source/x264/." "$BASE/x264/"
cp -a "$ROOT/native/source/ffmpeg/." "$BASE/ffmpeg/"
cd "$BASE/x264"
CC="$BASE/tools/cc" AR="$LLVM_TOOLS/llvm-ar" RANLIB="$LLVM_TOOLS/llvm-ranlib" \
 ./configure --prefix="$PREFIX" --host="$HOST" --enable-static --disable-cli \
 --disable-opencl --disable-asm --disable-thread --enable-pic --extra-cflags='-O3'
make -j "${JOBS:-4}"
make install
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
cd "$BASE/ffmpeg"
THREAD_FLAGS=()
if [[ "$OS" == darwin ]]; then THREAD_FLAGS=(--enable-pthreads); fi
./configure --prefix="$PREFIX" --enable-cross-compile --target-os="$OS" --arch="$ARCH" \
 --cc="$BASE/tools/cc" --ar="$LLVM_TOOLS/llvm-ar" --ranlib="$LLVM_TOOLS/llvm-ranlib" \
 --nm="$LLVM_TOOLS/llvm-nm" --strip="$LLVM_TOOLS/llvm-strip" \
 --enable-gpl --enable-libx264 --disable-debug --disable-doc --disable-ffplay \
 "${THREAD_FLAGS[@]}" --disable-autodetect --disable-devices --disable-asm --disable-x86asm --disable-inline-asm \
 --enable-static --disable-shared --disable-videotoolbox --disable-audiotoolbox \
 --disable-securetransport --extra-cflags="-O3 -I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib"
make -j "${JOBS:-4}"
make install
printf 'Built %s in %s/bin\n' "$TARGET" "$PREFIX"
