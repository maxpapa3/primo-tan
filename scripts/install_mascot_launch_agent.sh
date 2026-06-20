#!/usr/bin/env bash
set -euo pipefail

LABEL="ai.radxa.mascot"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="$HOME/.radxa-mascot"
PLIST_SRC="${PROJECT_DIR}/launchd/${LABEL}.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/radxa-mascot"
UID_VALUE="$(id -u)"
PUBLIC_BASE_URL="${MASCOT_PUBLIC_BASE_URL:-}"

if [[ -z "$PUBLIC_BASE_URL" ]]; then
  MAC_IP="$(ipconfig getifaddr en1 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || true)"
  PUBLIC_BASE_URL="http://${MAC_IP:-127.0.0.1}:${MASCOT_PORT:-8765}"
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
rm -rf "$RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR"
cp -R "${PROJECT_DIR}/mac_mini" "$RUNTIME_DIR/"
chmod +x "$RUNTIME_DIR/mac_mini/"*.sh "$RUNTIME_DIR/mac_mini/"*.py
sed \
  -e "s#__HOME__#$HOME#g" \
  -e "s#__MASCOT_PUBLIC_BASE_URL__#$PUBLIC_BASE_URL#g" \
  "$PLIST_SRC" > "$PLIST_DEST"

launchctl bootout "gui/${UID_VALUE}" "$PLIST_DEST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UID_VALUE}" "$PLIST_DEST"
launchctl kickstart -k "gui/${UID_VALUE}/${LABEL}"

echo "installed and started ${LABEL}"
echo "runtime:"
echo "  ${RUNTIME_DIR}"
echo "logs:"
echo "  ${LOG_DIR}/stdout.log"
echo "  ${LOG_DIR}/stderr.log"
