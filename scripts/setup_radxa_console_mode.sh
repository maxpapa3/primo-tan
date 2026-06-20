#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
RADXA_KEY="${RADXA_KEY:-$HOME/.ssh/radxa_zero3w_ed25519}"
REMOTE_HELPER="/usr/local/sbin/primo-console-mode"
REMOTE_SUDOERS="/etc/sudoers.d/primo-console-mode"

scp -i "$RADXA_KEY" radxa_client/primo_console_mode.sh "$RADXA_USER@$RADXA_HOST:/tmp/primo-console-mode"

ssh -tt -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" "
  set -e
  sudo install -o root -g root -m 0755 /tmp/primo-console-mode '$REMOTE_HELPER'
  {
    printf '%s\n' '$RADXA_USER ALL=(root) NOPASSWD: $REMOTE_HELPER'
    printf '%s\n' '$RADXA_USER ALL=(root) NOPASSWD: /sbin/shutdown -h now'
  } | sudo tee '$REMOTE_SUDOERS' >/dev/null
  sudo chmod 0440 '$REMOTE_SUDOERS'
  sudo visudo -cf '$REMOTE_SUDOERS'
  sudo '$REMOTE_HELPER' status
"

echo "installed $REMOTE_HELPER and sudoers rule"
