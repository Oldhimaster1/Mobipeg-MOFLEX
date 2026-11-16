#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ $# -lt 1 ]; then echo 'Usage: V8_ENCODE_STEREO.command input_HSBS.mp4 [additional options]' >&2; exit 2; fi
INPUT="$1";shift
python3 "$ROOT/V8/encode_stereo_v8.py" "$INPUT" --encoder "$ROOT/local/bin/ffmpeg" --probe "$ROOT/local/bin/ffprobe" "$@"
