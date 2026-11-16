#!/bin/bash
# Explicit faster encode, at a measured quality tradeoff versus subme9.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
MOBIPEG_PROFILE=fast bash "$ROOT/encode_macos.sh" 2d "$@"
