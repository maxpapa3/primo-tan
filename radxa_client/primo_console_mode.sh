#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
VTCON="/sys/class/vtconsole/vtcon1/bind"
SERVICE="whisplay-console.service"

case "$MODE" in
  mascot)
    systemctl stop "$SERVICE" >/dev/null 2>&1 || true
    if [ -w "$VTCON" ]; then
      printf '0' > "$VTCON" || true
    fi
    # Clear any old console pixels once fbcon is detached.
    if [ -w /dev/fb0 ]; then
      dd if=/dev/zero of=/dev/fb0 bs=134400 count=1 conv=notrunc status=none 2>/dev/null || true
    fi
    ;;
  console)
    pkill -f '[f]ace_display.py' >/dev/null 2>&1 || true
    if [ -w "$VTCON" ]; then
      printf '1' > "$VTCON" || true
    fi
    systemctl start "$SERVICE" >/dev/null 2>&1 || true
    chvt 1 >/dev/null 2>&1 || true
    ;;
  status)
    echo "service=$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
    if [ -r "$VTCON" ]; then
      echo "vtcon1=$(cat "$VTCON")"
    fi
    ;;
  *)
    echo "usage: $0 mascot|console|status" >&2
    exit 2
    ;;
esac

