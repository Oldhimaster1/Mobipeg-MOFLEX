#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
FFMPEG="$ROOT/local/bin/ffmpeg"
FFPROBE="$ROOT/local/bin/ffprobe"
if [[ ! -x "$FFMPEG" || ! -x "$FFPROBE" ]]; then
  echo "Run BUILD_FOR_MAC.command first."
  exit 1
fi
RESULTS="$ROOT/test_results"
mkdir -p "$RESULTS"
TEST_VIDEO="$RESULTS/TEST_2D_QP12.moflex"
echo "Encoding 60 synthetic frames with our actual custom encoder..."
MOBI_SUBME=9 MOBI_SKIP=0 "$FFMPEG" -y -nostdin -hide_banner -loglevel error \
  -f lavfi -i 'testsrc2=size=400x240:rate=30000/1001' -frames:v 60 \
  -an -c:v mobiclip -mobiclip 1 -qp 12 -preset medium \
  -me_method hex -g 60 -mo_layout 6 -f moflex "$TEST_VIDEO"
COUNT="$("$FFPROBE" -v error -select_streams v:0 -count_packets \
  -show_entries stream=nb_read_packets -of default=noprint_wrappers=1:nokey=1 "$TEST_VIDEO" | awk 'match($0, /[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }')"
[[ "$COUNT" == 60 ]] || { echo "FAIL: Expected 60 frames, got $COUNT"; exit 1; }
"$FFMPEG" -nostdin -hide_banner -loglevel error -xerror -i "$TEST_VIDEO" -f null -
echo "PASS: 60 frames encoded and decoded successfully."
if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$TEST_VIDEO"; fi
echo "Output: $TEST_VIDEO"
