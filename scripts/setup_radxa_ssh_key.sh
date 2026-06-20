#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
KEY_PATH="${KEY_PATH:-$HOME/.ssh/radxa_zero3w_ed25519}"

if [ ! -f "${KEY_PATH}" ]; then
  ssh-keygen -t ed25519 -f "${KEY_PATH}" -N "" -C "mac-mini-to-radxa-zero3w"
fi

ssh-copy-id -i "${KEY_PATH}.pub" "${RADXA_USER}@${RADXA_HOST}"

echo
echo "Test with:"
echo "  ssh -i ${KEY_PATH} ${RADXA_USER}@${RADXA_HOST}"
echo
echo "For scripts, add this to ~/.ssh/config:"
echo "Host radxa-zero3w"
echo "  HostName ${RADXA_HOST}"
echo "  User ${RADXA_USER}"
echo "  IdentityFile ${KEY_PATH}"
