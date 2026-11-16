#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ $# -lt 1 ]; then echo 'Usage: V7_LATEST_STEREO.command source_HSBS.mp4 [options...]'; exit 1; fi
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" "$ROOT/V7/encode_stereo_v7.py" "$1" --encoder "$ROOT/local/bin/ffmpeg" --probe "$ROOT/local/bin/ffprobe" "${@:2}"
