#!/bin/bash
# Experimental V11 quality profile for H-SBS/F-SBS files on macOS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'Run V11/encode_stereo_v11.py directly on Linux.'
  exit 1
fi
if [[ ! -x "$ROOT/local/bin/ffmpeg" || ! -x "$ROOT/local/bin/ffprobe" ]]; then
  echo 'First run BUILD_FOR_MAC.command to compile the native encoder.'
  exit 1
fi
if [[ $# -gt 0 ]]; then
  VIDEO="$1"
else
  VIDEO="$(osascript -e 'POSIX path of (choose file with prompt "Choose H-SBS/F-SBS 3D movie")')" || exit 0
fi
python3 "$ROOT/V11/encode_stereo_v11.py" "$VIDEO" \
  --encoder "$ROOT/local/bin/ffmpeg" --probe "$ROOT/local/bin/ffprobe" \
  --workers "${MOBIPEG_V11_WORKERS:-5}"
