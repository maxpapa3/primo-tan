#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
RADXA_KEY="${RADXA_KEY:-$HOME/.ssh/radxa_zero3w_ed25519}"
MAC_HOST="${MAC_HOST:-$(ipconfig getifaddr en1 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)}"
REMOTE_DIR="${REMOTE_DIR:-/home/radxa/radxa-ai-mascot}"
SERVICE_NAME="primo-mascot.service"

if [[ -z "${RADXA_SUDO_PASSWORD:-}" ]]; then
  read -r -s -p "Radxa sudo password: " RADXA_SUDO_PASSWORD
  echo
fi

if ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" "systemctl list-unit-files '$SERVICE_NAME' >/dev/null 2>&1"; then
  ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" \
    "printf '%s\n' '$RADXA_SUDO_PASSWORD' | sudo -S systemctl restart '$SERVICE_NAME'"
else
  ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" \
    "cd '$REMOTE_DIR' && pkill -f '[v]oice_client.py|[p]rimo_supervisor.py' >/dev/null 2>&1 || true"

  ssh -f -n -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" \
    "cd '$REMOTE_DIR' && nohup python3 -u primo_supervisor.py --server 'http://${MAC_HOST}:8765' --start-inactive > voice_client.log 2>&1 < /dev/null &"
fi

echo "started AI mascot supervisor"
echo "log: ssh -i $RADXA_KEY $RADXA_USER@$RADXA_HOST 'tail -f $REMOTE_DIR/voice_client.log'"
