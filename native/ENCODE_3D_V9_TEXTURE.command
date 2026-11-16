#!/bin/bash
# macOS shortcut for the experimental edge-protected MobiPEG V9 3D encoder.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'This double-click shortcut is intended for macOS.'
  exit 1
fi
if [[ ! -x "$ROOT/local/bin/ffmpeg" || ! -x "$ROOT/local/bin/ffprobe" ]]; then
  echo 'Build MobiPEG first: double-click BUILD_FOR_MAC.command.'
  exit 1
fi
if [[ $# -gt 0 ]]; then
  VIDEO="$1"
else
  VIDEO="$(osascript -e 'POSIX path of (choose file with prompt "Choose an H-SBS or F-SBS 3D movie")')" || exit 0
fi
python3 "$ROOT/V9/encode_stereo_v9.py" "$VIDEO" \
  --encoder "$ROOT/local/bin/ffmpeg" --probe "$ROOT/local/bin/ffprobe" \
  --profile texture --workers "${MOBIPEG_V9_WORKERS:-5}"
