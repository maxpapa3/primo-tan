#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
RADXA_KEY="${RADXA_KEY:-$HOME/.ssh/radxa_zero3w_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/home/radxa/radxa-ai-mascot}"

ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" \
  "echo '--- service ---'; systemctl --no-pager --full status primo-mascot.service 2>/dev/null | sed -n '1,40p' || true; echo '--- process ---'; pgrep -af '[v]oice_client.py|[p]rimo_supervisor.py' || true; echo '--- console ---'; sudo -n /usr/local/sbin/primo-console-mode status 2>/dev/null || true; echo '--- log ---'; tail -n 100 '$REMOTE_DIR/voice_client.log' 2>/dev/null || true"
