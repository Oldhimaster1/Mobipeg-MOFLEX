#!/usr/bin/env bash
# Rebuild changed FFmpeg objects and relink both existing codec configurations.
# Run the full build-wasm/build-simd scripts first to initialize these trees.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${EMSDK:?Set EMSDK}"
source "$EMSDK/emsdk_env.sh"
BASE="$ROOT/.build/ffmpeg"
PREFIX="$ROOT/.build/wasm-prefix/lib"
test -f "$ROOT/.build/x264-simd/libx264.a"
cp "$BASE/ffbuild/config.mak" "$BASE/ffbuild/config.mak.relink-save"
cp "$PREFIX/libx264.a" "$PREFIX/libx264.relink-save.a"
cleanup(){ cp "$BASE/ffbuild/config.mak.relink-save" "$BASE/ffbuild/config.mak"; cp "$PREFIX/libx264.relink-save.a" "$PREFIX/libx264.a"; }
trap cleanup EXIT
cp "$ROOT/native/source/ffmpeg/libavformat/moflex.c" "$BASE/libavformat/moflex.c"
for variant in engine engine-simd; do
 cp "$BASE/ffbuild/config.mak.relink-save" "$BASE/ffbuild/config.mak"
 if [[ "$variant" == engine-simd ]]; then
  cp "$ROOT/.build/x264-simd/libx264.a" "$PREFIX/libx264.a"
  printf '\nLDFLAGS += -msimd128\n' >> "$BASE/ffbuild/config.mak"
 else
  cp "$ROOT/.build/x264/libx264.a" "$PREFIX/libx264.a"
 fi
 emmake make -C "$BASE" -j "${JOBS:-8}" -W fftools/ffmpeg.o ffmpeg_g
 cp "$BASE/ffmpeg_g" "$ROOT/dist/$variant/mobipeg.js"
 sed -i 's/ffmpeg_g.wasm/mobipeg.wasm/g' "$ROOT/dist/$variant/mobipeg.js"
 cp "$BASE/ffmpeg_g.wasm" "$ROOT/dist/$variant/mobipeg.wasm"
done
