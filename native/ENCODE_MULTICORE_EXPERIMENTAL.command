#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
exec /bin/bash "$ROOT/encode_macos.sh" multicore "$@"
