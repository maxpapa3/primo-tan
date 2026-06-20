#!/usr/bin/env bash
set -euo pipefail

LABEL="ai.radxa.mascot"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_VALUE="$(id -u)"

launchctl bootout "gui/${UID_VALUE}" "$PLIST_DEST" >/dev/null 2>&1 || true
rm -f "$PLIST_DEST"
echo "uninstalled ${LABEL}"

