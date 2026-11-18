#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${EMSDK:?Set EMSDK to an installed emsdk directory}"
"$EMSDK/upstream/bin/clang" --target=wasm32 -O3 -nostdlib -fno-builtin \
  -Wl,--no-entry -Wl,--export=initialize -Wl,--export=compress \
  -Wl,--export=data_address -Wl,--export=state_address -Wl,--export-memory \
  -Wl,--initial-memory=2097152 -Wl,--max-memory=2097152 \
  "$ROOT/native/hash/sha256.c" -o "$ROOT/cia-sha256-core.wasm"
cp "$ROOT/cia-sha256-core.wasm" "$ROOT/dist/cia-sha256-core.wasm"
