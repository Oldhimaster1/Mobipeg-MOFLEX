#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${EMSDK:?Set EMSDK to an installed emsdk directory (tested 4.0.10)}"
source "$EMSDK/emsdk_env.sh"
PREFIX="$ROOT/.build/wasm-prefix"
mkdir -p "$ROOT/.build/x264" "$ROOT/.build/ffmpeg" "$PREFIX" "$ROOT/dist/engine"
cp -a "$ROOT/native/source/x264/." "$ROOT/.build/x264/"
cp -a "$ROOT/native/source/ffmpeg/." "$ROOT/.build/ffmpeg/"
cd "$ROOT/.build/x264"
emconfigure ./configure --prefix="$PREFIX" --host=wasm32-unknown-linux --enable-static --disable-cli --disable-opencl --disable-asm --disable-thread --enable-pic --extra-cflags='-O3 -pthread'
emmake make -j "${JOBS:-8}"
emmake make install
cd "$ROOT/.build/ffmpeg"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export EM_PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
emconfigure ./configure --prefix="$PREFIX" --cc=emcc --cxx=em++ --ar=emar --ranlib=emranlib --nm=emnm --enable-cross-compile --target-os=none --arch=wasm32 --enable-gpl --enable-libx264 --disable-autodetect --disable-asm --disable-x86asm --disable-inline-asm --enable-pthreads --disable-w32threads --disable-os2threads --disable-network --disable-devices --disable-doc --disable-debug --disable-ffplay --disable-ffprobe --disable-shared --enable-static --extra-cflags="-O3 -pthread -I$PREFIX/include" --extra-ldflags="-O3 -pthread -L$PREFIX/lib -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=33554432 -sMAXIMUM_MEMORY=2147483648 -sSTACK_SIZE=5242880 -sPTHREAD_POOL_SIZE=8 -sMODULARIZE=1 -sEXPORT_NAME=createMobiPEG -sINVOKE_RUN=0 -sEXIT_RUNTIME=1 -sEXPORTED_RUNTIME_METHODS=callMain,FS,ENV,PThread,HEAPU8 -sFORCE_FILESYSTEM=1 -lworkerfs.js -sENVIRONMENT=web,worker,node"
emmake make -j "${JOBS:-8}" ffmpeg_g
cp ffmpeg_g "$ROOT/dist/engine/mobipeg.js"
sed -i 's/ffmpeg_g.wasm/mobipeg.wasm/g' "$ROOT/dist/engine/mobipeg.js"
cp ffmpeg_g.wasm "$ROOT/dist/engine/mobipeg.wasm"
node "$ROOT/scripts/provenance.mjs"
