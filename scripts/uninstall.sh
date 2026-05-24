#!/usr/bin/env bash
# Remove the Inky Studio service + CLI wrapper. Leaves the install dir and
# data dir in place so you keep your photos and credentials.
set -euo pipefail

SERVICE_NAME="inky-studio.service"
LEGACY_SERVICE_NAME="inky-photo-frame.service"

echo "→ Stopping and disabling ${SERVICE_NAME}…"
sudo systemctl stop "${SERVICE_NAME}" || true
sudo systemctl disable "${SERVICE_NAME}" || true
sudo rm -f "/etc/systemd/system/${SERVICE_NAME}"
sudo systemctl daemon-reload

echo "→ Removing CLI wrapper /usr/local/bin/inky-studio…"
sudo rm -f /usr/local/bin/inky-studio

if systemctl list-unit-files --type=service | grep -q "^${LEGACY_SERVICE_NAME}"; then
  echo "→ Re-enabling legacy ${LEGACY_SERVICE_NAME}…"
  sudo systemctl enable --now "${LEGACY_SERVICE_NAME}" || true
fi

cat <<EOF

Done. Photos and credentials are preserved under /var/lib/inky-studio.
The code at /home/pi/inky-studio is still there — delete it manually if desired.
EOF
