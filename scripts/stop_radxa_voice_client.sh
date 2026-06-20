#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
RADXA_KEY="${RADXA_KEY:-$HOME/.ssh/radxa_zero3w_ed25519}"
SERVICE_NAME="primo-mascot.service"

if [[ -z "${RADXA_SUDO_PASSWORD:-}" ]]; then
  read -r -s -p "Radxa sudo password: " RADXA_SUDO_PASSWORD
  echo
fi

ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" \
  "if systemctl list-unit-files '$SERVICE_NAME' >/dev/null 2>&1; then \
     printf '%s\n' '$RADXA_SUDO_PASSWORD' | sudo -S systemctl stop '$SERVICE_NAME'; \
   fi; \
   pkill -f '[v]oice_client.py|[p]rimo_supervisor.py' >/dev/null 2>&1 || true"

ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" \
  "printf '%s\n' '$RADXA_SUDO_PASSWORD' | sudo -S /usr/local/sbin/primo-console-mode console"

echo "stopped Primo-tan supervisor"
