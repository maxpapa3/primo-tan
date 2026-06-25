#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
RADXA_KEY="${RADXA_KEY:-$HOME/.ssh/radxa_zero3w_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/home/radxa/radxa-ai-mascot}"

ssh -i "${RADXA_KEY}" "${RADXA_USER}@${RADXA_HOST}" "mkdir -p '${REMOTE_DIR}'"
scp -i "${RADXA_KEY}" radxa_client/*.py radxa_client/*.sh "${RADXA_USER}@${RADXA_HOST}:${REMOTE_DIR}/"
if [[ -d radxa_client/assets ]]; then
  ssh -i "${RADXA_KEY}" "${RADXA_USER}@${RADXA_HOST}" "mkdir -p '${REMOTE_DIR}/assets'"
  scp -i "${RADXA_KEY}" radxa_client/assets/* "${RADXA_USER}@${RADXA_HOST}:${REMOTE_DIR}/assets/"
fi
ssh -i "${RADXA_KEY}" "${RADXA_USER}@${RADXA_HOST}" "chmod +x '${REMOTE_DIR}/'*.py"
