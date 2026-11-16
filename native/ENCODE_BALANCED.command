#!/bin/bash
# Compromise between maximum-quality and fastest encoding.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
MOBIPEG_PROFILE=balanced bash "$ROOT/encode_macos.sh" 2d "$@"
