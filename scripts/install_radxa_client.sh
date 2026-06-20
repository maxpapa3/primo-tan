#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
RADXA_KEY="${RADXA_KEY:-$HOME/.ssh/radxa_zero3w_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/home/radxa/radxa-ai-mascot}"

ssh -i "${RADXA_KEY}" "${RADXA_USER}@${RADXA_HOST}" "mkdir -p '${REMOTE_DIR}'"
scp -i "${RADXA_KEY}" -r radxa_client/* "${RADXA_USER}@${RADXA_HOST}:${REMOTE_DIR}/"
ssh -i "${RADXA_KEY}" "${RADXA_USER}@${RADXA_HOST}" "chmod +x '${REMOTE_DIR}/'*.py"
