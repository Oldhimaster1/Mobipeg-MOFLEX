#!/bin/bash
# Experimental intra4x4 prediction shortlist. Faster, but NOT lossless.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
export MOBIPEG_PROFILE=quality
export MOBI_INTRA_RD_CAP=3
export MOBI_INTRA_RD_POLICY=1
exec /bin/bash "$ROOT/encode_macos.sh" 2d "$@"
