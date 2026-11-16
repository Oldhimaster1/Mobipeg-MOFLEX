#!/usr/bin/env bash
# After build-wasm.sh: rebuild ONLY the codec backend with WASM SIMD, then relink.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${EMSDK:?Set EMSDK}"
source "$EMSDK/emsdk_env.sh"
mkdir -p "$ROOT/.build/x264-simd" "$ROOT/dist/engine-simd"
cp -a "$ROOT/.build/x264/." "$ROOT/.build/x264-simd/"
cd "$ROOT/.build/x264-simd"
emmake make clean
sed -i 's/-fno-tree-vectorize/-ftree-vectorize -msimd128/g' config.mak
emmake make -j "${JOBS:-8}"
cp "$ROOT/.build/wasm-prefix/lib/libx264.a" "$ROOT/.build/wasm-prefix/lib/libx264-scalar.a"
cp libx264.a "$ROOT/.build/wasm-prefix/lib/libx264.a"
cd "$ROOT/.build/ffmpeg"
cp ffbuild/config.mak ffbuild/config.mak.pre-simd
trap 'cp ffbuild/config.mak.pre-simd ffbuild/config.mak; cp "$ROOT/.build/wasm-prefix/lib/libx264-scalar.a" "$ROOT/.build/wasm-prefix/lib/libx264.a"' EXIT
printf '\nLDFLAGS += -msimd128\n' >> ffbuild/config.mak
emmake make -j "${JOBS:-8}" -W fftools/ffmpeg.o ffmpeg_g
cp ffmpeg_g "$ROOT/dist/engine-simd/mobipeg.js"
sed -i 's/ffmpeg_g.wasm/mobipeg.wasm/g' "$ROOT/dist/engine-simd/mobipeg.js"
cp ffmpeg_g.wasm "$ROOT/dist/engine-simd/mobipeg.wasm"
