#!/usr/bin/env bash
set -euo pipefail

LABEL="ai.radxa.mascot"
UID_VALUE="$(id -u)"

launchctl print "gui/${UID_VALUE}/${LABEL}"

