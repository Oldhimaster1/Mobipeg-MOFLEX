#!/bin/bash
# 400x240, near-29.97 FPS, QP12, skip0, hex, 60 GOP.
# Select an explicit quality/speed tradeoff with MOBIPEG_PROFILE.
# Source-aware TV-range conversion and strict output decoding.
set -euo pipefail

MODE="${1:-2d}"
if [[ $# -gt 0 ]]; then shift; fi
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
FFMPEG="${MOBIPEG_TEST_FFMPEG:-$ROOT/local/bin/ffmpeg}"
FFPROBE="${MOBIPEG_TEST_FFPROBE:-$ROOT/local/bin/ffprobe}"
if [[ ! -x "$FFMPEG" || ! -x "$FFPROBE" ]]; then
  echo "Our custom MobiPEG encoder hasn't been built on this computer yet."
  echo "Run BUILD_FOR_MAC.command first."
  exit 1
fi

if [[ $# -gt 0 ]]; then
  INPUT="$1"
else
  if ! command -v osascript >/dev/null 2>&1; then
    echo "Usage: bash encode_macos.sh $MODE /path/to/movie.mp4"
    exit 1
  fi
  INPUT="$(osascript -e 'POSIX path of (choose file with prompt "Pick the video for MobiPEG")')" || exit 0
fi
if [[ ! -f "$INPUT" ]]; then
  echo "Source video not found: $INPUT"
  exit 1
fi

case "$MODE" in
  2d|multicore) LAYOUT=6; LABEL=2D ;;
  full-sbs) LAYOUT=4; LABEL=3D_FULL_SBS ;;
  half-sbs) LAYOUT=4; LABEL=3D_HALF_SBS ;;
  *) echo "Unknown mode: $MODE"; exit 1 ;;
esac
PROFILE="${MOBIPEG_PROFILE:-quality}"
case "$PROFILE" in
  quality) SEARCH_DEPTH=9; PROFILE_SUFFIX='' ;;
  balanced) SEARCH_DEPTH=7; PROFILE_SUFFIX='_BALANCED' ;;
  fast) SEARCH_DEPTH=5; PROFILE_SUFFIX='_FAST' ;;
  fastest) SEARCH_DEPTH=2; PROFILE_SUFFIX='_FASTEST' ;;
  *) echo "Invalid MOBIPEG_PROFILE: $PROFILE (quality, balanced, fast, fastest)"; exit 1 ;;
esac
BASE="$(basename "$INPUT")"
STEM="${BASE%.*}"
DIR="$(cd "$(dirname "$INPUT")" && pwd -P)"
TARGET="$DIR/${STEM}_MobiPEG_${LABEL}${PROFILE_SUFFIX}.moflex"
if [[ -e "$TARGET" ]]; then
  IDX=2
  while [[ -e "$DIR/${STEM}_MobiPEG_${LABEL}${PROFILE_SUFFIX}_${IDX}.moflex" ]]; do
    IDX=$((IDX+1))
  done
  TARGET="$DIR/${STEM}_MobiPEG_${LABEL}${PROFILE_SUFFIX}_${IDX}.moflex"
fi

echo "Source: $INPUT"
echo "Output: $TARGET"
echo "Profile: $PROFILE (QP12 / subme${SEARCH_DEPTH} / skip0 / hex / 60 GOP; 400x240 per eye)"
if [[ "${MOBI_INTRA_RD_CAP:-0}" != "0" ]]; then
  echo "EXPERIMENTAL intra-prediction refinement cap=${MOBI_INTRA_RD_CAP} policy=${MOBI_INTRA_RD_POLICY:-0}."
  echo "This is NOT bit-identical to the default quality encode. Test it on real 3DS hardware."
fi
export MOBI_SUBME="$SEARCH_DEPTH" MOBI_SKIP=0
START_TIME="$SECONDS"

if [[ "$MODE" == multicore ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for experimental multicore encoding (from Xcode CLT or Python.org)."
    exit 1
  fi
  echo "EXPERIMENTAL: GOP-aligned parallelism; a different encoder scene decision can still change output."
  python3 "$ROOT/tools/mobipeg_parallel_v4.py" "$INPUT" "$TARGET" \
    --ffmpeg "$FFMPEG" --ffprobe "$FFPROBE" --jobs "${MOBIPEG_JOBS:-4}" \
    --chunk-frames 60 --seam-mode gop --qp 12 --subme "$SEARCH_DEPTH" --skip 0 \
    --fps 30000/1001 --report "$TARGET.parallel.json"
  exit $?
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mobipeg_friend.XXXXXXXX")"
trap 'rm -rf -- "$TMP_DIR"' EXIT
VIDEO_ONLY="$TMP_DIR/video_only.moflex"
FINAL_TMP="$TMP_DIR/final.moflex"
SCALE='scale=400:240:force_original_aspect_ratio=decrease:force_divisible_by=2:in_range=auto:out_range=tv:flags=lanczos,pad=400:240:(ow-iw)/2:(oh-ih)/2,setsar=1'

echo "Encoding custom Mobiclip video..."
if [[ "$MODE" == 2d ]]; then
  "$FFMPEG" -y -nostdin -hide_banner -loglevel error -stats -i "$INPUT" \
    -map 0:v:0 -vf "fps=30000/1001,$SCALE,format=yuv420p" \
    -an -c:v mobiclip -mobiclip 1 -qp 12 -preset medium \
    -me_method hex -g 60 -mo_layout "$LAYOUT" -f moflex "$VIDEO_ONLY"
else
  SAR=1
  [[ "$MODE" == half-sbs ]] && SAR=2
  EYE="setsar=$SAR,$SCALE"
  FILTER="[0:v:0]fps=30000/1001,split=2[left][right];[left]crop=iw/2:ih:0:0,$EYE[l];[right]crop=iw/2:ih:iw/2:0,$EYE[r];[l][r]hstack=inputs=2,format=yuv420p[vid]"
  "$FFMPEG" -y -nostdin -hide_banner -loglevel error -stats -i "$INPUT" \
    -filter_complex "$FILTER" -map '[vid]' \
    -an -c:v mobiclip -mobiclip 1 -qp 12 -preset medium \
    -me_method hex -g 60 -mo_layout "$LAYOUT" -f moflex "$VIDEO_ONLY"
fi

COUNT_RAW="$("$FFPROBE" -v error -select_streams v:0 -count_packets \
  -show_entries stream=nb_read_packets -of default=noprint_wrappers=1:nokey=1 "$VIDEO_ONLY")"
FRAMES="$(printf '%s\n' "$COUNT_RAW" | awk 'match($0, /[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }')"
if [[ -z "$FRAMES" || "$FRAMES" -le 0 ]]; then
  echo "ERROR: Could not verify encoded video frame count."
  exit 1
fi
DURATION="$(awk -v n="$FRAMES" 'BEGIN { printf "%.7f", n * 1001 / 30000 }')"

HAS_AUDIO="$("$FFPROBE" -v error -select_streams a:0 \
  -show_entries stream=index -of csv=p=0 "$INPUT" | awk '/^[0-9]+/ { print 1; exit }')"
if [[ "$HAS_AUDIO" == 1 ]]; then
  echo "Muxing original audio as MOFLEX ADPCM..."
  "$FFMPEG" -y -nostdin -hide_banner -loglevel error -stats \
    -i "$VIDEO_ONLY" -i "$INPUT" -map 0:v:0 -map 1:a:0 \
    -c:v copy -c:a pcm_s16le -ar 44100 -ac 2 -af apad \
    -mo_audio adpcm -mo_layout "$LAYOUT" -t "$DURATION" \
    -f moflex "$FINAL_TMP"
else
  cp "$VIDEO_ONLY" "$FINAL_TMP"
fi

echo "Verifying complete video decode..."
"$FFMPEG" -nostdin -hide_banner -loglevel error -xerror -i "$FINAL_TMP" \
  -map 0:v:0 -f null -
if [[ "$HAS_AUDIO" == 1 ]]; then
  "$FFMPEG" -nostdin -hide_banner -loglevel error -xerror -i "$FINAL_TMP" \
    -map 0:a:0 -f null -
fi
FINAL_COUNT="$("$FFPROBE" -v error -select_streams v:0 -count_packets \
  -show_entries stream=nb_read_packets -of default=noprint_wrappers=1:nokey=1 "$FINAL_TMP" | awk 'match($0, /[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }')"
[[ "$FINAL_COUNT" == "$FRAMES" ]] || { echo "ERROR: Remux frame count changed ($FRAMES -> $FINAL_COUNT)."; exit 1; }

mv "$FINAL_TMP" "$TARGET"
ELAPSED=$((SECONDS-START_TIME))
echo "SUCCESS: $TARGET"
echo "Decoded frames: $FRAMES; elapsed: ${ELAPSED}s"
if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$TARGET"; fi
echo "Please check playback, audio sync and 3D slider on actual 3DS hardware."
