#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec python3 mac_mini/mascot_server.py --host "${MASCOT_HOST:-0.0.0.0}" --port "${MASCOT_PORT:-8765}"

