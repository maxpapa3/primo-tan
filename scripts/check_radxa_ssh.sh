#!/usr/bin/env bash
set -euo pipefail

RADXA_HOST="${RADXA_HOST:-radxa-zero3w.local}"
RADXA_USER="${RADXA_USER:-radxa}"
RADXA_KEY="${RADXA_KEY:-$HOME/.ssh/radxa_zero3w_ed25519}"

ssh -i "${RADXA_KEY}" -o BatchMode=yes -o ConnectTimeout=5 "${RADXA_USER}@${RADXA_HOST}" 'printf "connected: "; hostname; uname -a'
