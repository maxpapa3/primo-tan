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

ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" "mkdir -p '$REMOTE_DIR'"
scp -i "$RADXA_KEY" radxa_client/*.py radxa_client/*.sh "$RADXA_USER@$RADXA_HOST:$REMOTE_DIR/"
ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" "chmod +x '$REMOTE_DIR/'*.py"

ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" "cat > /tmp/$SERVICE_NAME" <<EOF
[Unit]
Description=AI mascot button supervisor
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$RADXA_USER
WorkingDirectory=$REMOTE_DIR
ExecStart=/usr/bin/python3 -u $REMOTE_DIR/primo_supervisor.py --server http://$MAC_HOST:8765 --start-inactive
Restart=always
RestartSec=2
StandardOutput=append:$REMOTE_DIR/voice_client.log
StandardError=append:$REMOTE_DIR/voice_client.log

[Install]
WantedBy=multi-user.target
EOF

ssh -i "$RADXA_KEY" "$RADXA_USER@$RADXA_HOST" \
  "printf '%s\n' '$RADXA_SUDO_PASSWORD' | sudo -S mv /tmp/$SERVICE_NAME /etc/systemd/system/$SERVICE_NAME && \
   printf '%s\n' '$RADXA_SUDO_PASSWORD' | sudo -S systemctl daemon-reload && \
   printf '%s\n' '$RADXA_SUDO_PASSWORD' | sudo -S systemctl enable $SERVICE_NAME && \
   printf '%s\n' '$RADXA_SUDO_PASSWORD' | sudo -S systemctl restart $SERVICE_NAME"

echo "installed and started $SERVICE_NAME"
echo "status: ssh -i $RADXA_KEY $RADXA_USER@$RADXA_HOST 'systemctl status $SERVICE_NAME'"
