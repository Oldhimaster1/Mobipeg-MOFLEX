#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 V5/encode_stereo_v5.py "$@"
