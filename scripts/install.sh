#!/usr/bin/env bash
# Inky Studio installer for Raspberry Pi (Raspberry Pi OS, Debian bookworm or later).
#
# Idempotent — safe to re-run for updates. Disables the older inky-photo-frame
# service if found (only one process can drive the SPI bus on the Inky).
#
# Usage on the Pi:
#   curl -sSL https://raw.githubusercontent.com/mehdi7129/inky-studio/main/scripts/install.sh | bash
#
# Or, if you already cloned the repo:
#   bash scripts/install.sh

set -euo pipefail

REPO_URL="${INKY_STUDIO_REPO:-https://github.com/mehdi7129/inky-studio.git}"
INSTALL_DIR="${INKY_STUDIO_INSTALL_DIR:-/home/pi/inky-studio}"
DATA_DIR="${INKY_STUDIO_DATA_DIR:-/var/lib/inky-studio}"
SERVICE_NAME="inky-studio.service"
LEGACY_SERVICE_NAME="inky-photo-frame.service"
RUN_USER="${INKY_STUDIO_USER:-pi}"

if [[ "${EUID}" -eq 0 ]]; then
  echo "❌ Don't run this as root — run as the '${RUN_USER}' user. sudo will be invoked when needed." >&2
  exit 1
fi

echo "════════════════════════════════════════════════════════════════"
echo "  Inky Studio installer"
echo "════════════════════════════════════════════════════════════════"
echo "  Repo            : ${REPO_URL}"
echo "  Install dir     : ${INSTALL_DIR}"
echo "  Data dir        : ${DATA_DIR}"
echo "  Service         : ${SERVICE_NAME}"
echo "  Run as          : ${RUN_USER}"
echo "════════════════════════════════════════════════════════════════"
echo

# ── 1. Sanity checks ─────────────────────────────────────────────────────────
if [[ ! -e /dev/spidev0.0 ]]; then
  echo "⚠️  /dev/spidev0.0 not found. SPI is probably not enabled."
  echo "    Run: sudo raspi-config nonint do_spi 0  (then reboot)"
fi

# ── 2. System dependencies ───────────────────────────────────────────────────
echo "→ Installing system packages (apt)…"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  git python3 python3-venv python3-pip \
  fonts-dejavu fonts-dejavu-core \
  curl ca-certificates gnupg

# Node 22 (LTS) — Debian bookworm ships Node 18 which is too old for Vite 8.
NEED_NODE=1
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR=$(node -v | sed -E 's/^v([0-9]+)\..*/\1/')
  if [[ "${NODE_MAJOR}" -ge 20 ]]; then
    NEED_NODE=0
    echo "  Node $(node -v) already meets the Vite 8 requirement (>= 20)."
  fi
fi
if [[ "${NEED_NODE}" -eq 1 ]]; then
  echo "  Installing Node 22 from the NodeSource repo…"
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

# ── 3. Disable the older v2.0 service if present ─────────────────────────────
if systemctl list-unit-files --type=service | grep -q "^${LEGACY_SERVICE_NAME}"; then
  echo "→ Stopping legacy ${LEGACY_SERVICE_NAME}…"
  sudo systemctl stop "${LEGACY_SERVICE_NAME}" || true
  sudo systemctl disable "${LEGACY_SERVICE_NAME}" || true
  echo "  (disabled — re-enable with: sudo systemctl enable --now ${LEGACY_SERVICE_NAME})"
fi

# ── 4. Clone or update the repo ──────────────────────────────────────────────
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  echo "→ Updating existing checkout in ${INSTALL_DIR}…"
  git -C "${INSTALL_DIR}" fetch --depth=1 origin main
  git -C "${INSTALL_DIR}" reset --hard origin/main
else
  echo "→ Cloning ${REPO_URL} into ${INSTALL_DIR}…"
  sudo mkdir -p "$(dirname "${INSTALL_DIR}")"
  sudo chown "${RUN_USER}:${RUN_USER}" "$(dirname "${INSTALL_DIR}")"
  git clone --depth=1 "${REPO_URL}" "${INSTALL_DIR}"
fi

# ── 5. Python venv ───────────────────────────────────────────────────────────
echo "→ Setting up Python venv…"
cd "${INSTALL_DIR}/server"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -e ".[pi]"

# ── 6. Build the client ──────────────────────────────────────────────────────
echo "→ Building the frontend (this can take 1-2 min on a Pi Zero)…"
cd "${INSTALL_DIR}/client"
npm install --silent --no-audit --no-fund --no-progress
npm run build --silent

# ── 7. Data directory ────────────────────────────────────────────────────────
echo "→ Creating data directory ${DATA_DIR}…"
sudo install -d -m 0755 -o "${RUN_USER}" -g "${RUN_USER}" "${DATA_DIR}"
sudo install -d -m 0755 -o "${RUN_USER}" -g "${RUN_USER}" "${DATA_DIR}/photos"

# ── 8. CLI wrapper ───────────────────────────────────────────────────────────
echo "→ Installing CLI wrapper at /usr/local/bin/inky-studio…"
sudo install -m 0755 "${INSTALL_DIR}/scripts/inky-studio-cli" /usr/local/bin/inky-studio

# ── 9. systemd unit ──────────────────────────────────────────────────────────
echo "→ Writing systemd unit /etc/systemd/system/${SERVICE_NAME}…"
sudo tee "/etc/systemd/system/${SERVICE_NAME}" >/dev/null <<EOF
[Unit]
Description=Inky Studio — Web UI for the Inky e-ink photo frame
Documentation=https://github.com/mehdi7129/inky-studio
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}/server
Environment="INKY_STUDIO_DATA_DIR=${DATA_DIR}"
ExecStart=${INSTALL_DIR}/server/.venv/bin/inky-studio-server
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

# Restart to pick up any code change
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  sudo systemctl restart "${SERVICE_NAME}"
else
  sudo systemctl start "${SERVICE_NAME}"
fi

# ── 10. Welcome screen ───────────────────────────────────────────────────────
echo "→ Pushing welcome screen to the Inky display (takes ~40s)…"
# We have to stop the service briefly to claim the SPI bus from the same process.
sudo systemctl stop "${SERVICE_NAME}"
INKY_STUDIO_DATA_DIR="${DATA_DIR}" "${INSTALL_DIR}/server/.venv/bin/python" -m inky_web.welcome || \
  echo "  ⚠️  Welcome screen failed — service will still start normally."
sudo systemctl start "${SERVICE_NAME}"

# ── 11. Report ───────────────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}' || echo "<your-pi-ip>")
PWD_FILE="${DATA_DIR}/credentials.json"
PASSWORD=$(sudo cat "${PWD_FILE}" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])' 2>/dev/null || echo "(check ${PWD_FILE})")

echo
echo "════════════════════════════════════════════════════════════════"
echo "  ✅ Inky Studio installed"
echo "════════════════════════════════════════════════════════════════"
echo "  Open:      http://${IP}:8000"
echo "  Password:  ${PASSWORD}"
echo "  Service:   $(systemctl is-active "${SERVICE_NAME}")"
echo
echo "  CLI :"
echo "    inky-studio status         — service status"
echo "    inky-studio logs           — live logs"
echo "    inky-studio restart        — restart"
echo "    inky-studio welcome        — re-show welcome on the Inky"
echo "    inky-studio reset-password — generate a new password"
echo "    inky-studio update         — pull & rebuild"
echo "════════════════════════════════════════════════════════════════"
