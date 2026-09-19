#!/usr/bin/env bash
# Start ALVIOn locally.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${ALVION_PORT:-8080}"
echo "ALVIOn -> http://127.0.0.1:${PORT}"
exec python3 -m uvicorn alvion.main:app --host 127.0.0.1 --port "${PORT}" "$@"
