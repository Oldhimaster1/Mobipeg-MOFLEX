#!/bin/bash
# macOS V10 high-quality stereoscopic MobiPEG encoder.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'Use Python V10/encode_stereo_v10.py on Linux.'
  exit 1
fi
if [[ ! -x "$ROOT/local/bin/ffmpeg" || ! -x "$ROOT/local/bin/ffprobe" ]]; then
  echo 'First build the encoder with BUILD_FOR_MAC.command.'
  exit 1
fi
if [[ $# -gt 0 ]]; then
  VIDEO="$1"
else
  VIDEO="$(osascript -e 'POSIX path of (choose file with prompt "Select H-SBS/F-SBS 3D movie")')" || exit 0
fi
python3 "$ROOT/V10/encode_stereo_v10.py" "$VIDEO" \
  --encoder "$ROOT/local/bin/ffmpeg" --probe "$ROOT/local/bin/ffprobe" \
  --workers "${MOBIPEG_V10_WORKERS:-5}"
