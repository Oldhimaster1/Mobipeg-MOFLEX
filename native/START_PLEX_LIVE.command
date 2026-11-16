#!/bin/bash
# Live HTTP MOFLEX preview: standard Macs, local/Plex media, no Python packages.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x local/bin/ffmpeg ]]; then
    echo "Custom MobiPEG encoder missing. Run BUILD_FOR_MAC.command first."
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 required for the HTTP bridge (python3)."
    exit 1
fi

if [[ $# -eq 0 ]]; then
    echo "Drop or type a local MP4/MOV/MKV filename, then press Return:"
    read -r path
    set -- --source "$path"
elif [[ "$1" != --* ]]; then
    set -- --source "$1" "${@:2}"
fi

echo "Starting experimental HTTP MOFLEX bridge."
echo "Test endpoint: http://127.0.0.1:32550/live.moflex"
echo "NOTE: the CURRENT Clownsec/Big Top 3DS player cannot consume this live endpoint."
echo "For Plex: PLEX_TOKEN=... bash START_PLEX_LIVE.command --rating-key 1234"
exec python3 tools/plex_live_bridge.py --ffmpeg "$PWD/local/bin/ffmpeg" "$@"
