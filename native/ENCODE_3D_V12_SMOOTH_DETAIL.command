#!/bin/bash
# Experimental V12 smoothness + detail profile, macOS source build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'On Linux, use V12/encode_stereo_v12.py directly.'
  exit 1
fi
if [[ ! -x "$ROOT/local/bin/ffmpeg" || ! -x "$ROOT/local/bin/ffprobe" ]]; then
  echo 'First run BUILD_FOR_MAC.command to build MobiPEG.'
  exit 1
fi
if [[ $# -gt 0 ]]; then VIDEO="$1"
else VIDEO="$(osascript -e 'POSIX path of (choose file with prompt "Choose H-SBS or F-SBS 3D movie")')" || exit 0
fi
python3 "$ROOT/V12/encode_stereo_v12.py" "$VIDEO" \
  --encoder "$ROOT/local/bin/ffmpeg" --probe "$ROOT/local/bin/ffprobe" \
  --smoothness-profile "${MOBIPEG_V12_PROFILE:-balanced}" \
  --workers "${MOBIPEG_V12_WORKERS:-5}"
