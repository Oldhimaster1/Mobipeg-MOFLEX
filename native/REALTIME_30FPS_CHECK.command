#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
FFMPEG="$ROOT/local/bin/ffmpeg"
FFPROBE="$ROOT/local/bin/ffprobe"
if [[ ! -x "$FFMPEG" || ! -x "$FFPROBE" ]]; then
  echo "Build our custom encoder first: BUILD_FOR_MAC.command"
  exit 1
fi
OUT_DIR="$ROOT/test_results"
mkdir -p "$OUT_DIR"
OUTPUT="$OUT_DIR/BENCH_300_FRAMES_QP12.moflex"
echo "Benchmark: 300 frames, 400x240, QP12, subme9, skip0, hex."
echo "Measures full FFmpeg wall time on synthetic frames; not yet Plex live-stream speed."
START="$(date +%s)"
MOBI_SUBME=9 MOBI_SKIP=0 "$FFMPEG" -y -nostdin -hide_banner -loglevel error \
  -f lavfi -i 'testsrc2=size=400x240:rate=30000/1001' -frames:v 300 \
  -an -c:v mobiclip -mobiclip 1 -qp 12 -preset medium \
  -me_method hex -g 60 -mo_layout 6 -f moflex "$OUTPUT"
END="$(date +%s)"
ELAPSED=$((END-START))
if [[ "$ELAPSED" -lt 1 ]]; then ELAPSED=1; fi
COUNT="$("$FFPROBE" -v error -select_streams v:0 -count_packets \
  -show_entries stream=nb_read_packets -of default=noprint_wrappers=1:nokey=1 "$OUTPUT" | awk 'match($0, /[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }')"
[[ "$COUNT" == 300 ]] || { echo "FAIL: Frame count $COUNT, expected 300"; exit 1; }
"$FFMPEG" -nostdin -hide_banner -loglevel error -xerror -i "$OUTPUT" -f null -
FPS="$(awk -v n="$COUNT" -v s="$ELAPSED" 'BEGIN { printf "%.2f", n/s }')"
echo "Benchmark result: $FPS FPS ($COUNT frames in ${ELAPSED}s), decoded correctly."
echo "True streaming needs sustained >29.97 FPS plus decoder/network/audio overhead."
echo "Output: $OUTPUT"
