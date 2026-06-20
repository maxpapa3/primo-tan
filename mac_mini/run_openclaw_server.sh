#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export MASCOT_TALK_COMMAND="${MASCOT_TALK_COMMAND:-$PWD/mac_mini/openclaw_talk.py}"
if [[ -z "${MASCOT_PUBLIC_BASE_URL:-}" ]]; then
  MAC_IP="$(ipconfig getifaddr en1 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || true)"
  export MASCOT_PUBLIC_BASE_URL="http://${MAC_IP:-127.0.0.1}:${MASCOT_PORT:-8765}"
fi
PYTHON_BIN="${MASCOT_PYTHON:-$HOME/.radxa-mascot-stt/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
exec "$PYTHON_BIN" mac_mini/mascot_server.py --host "${MASCOT_HOST:-0.0.0.0}" --port "${MASCOT_PORT:-8765}"
