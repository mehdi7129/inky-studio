#!/usr/bin/env bash
# Inky Studio one-line installer for Raspberry Pi (Raspberry Pi OS / Debian).
#
#   curl -fsSL https://raw.githubusercontent.com/mehdi7129/inky-studio/main/install.sh | bash
#
# By default it installs the latest *prebuilt release* (the frontend is built in
# CI, so the Pi needs no Node and no build step). Set INKY_STUDIO_CHANNEL=source
# to build from the main branch instead.
#
# Idempotent — safe to re-run to repair or update an existing install.
#
# Environment overrides:
#   INKY_STUDIO_CHANNEL     release (default) | source
#   INKY_STUDIO_USER        service user (default: pi)
#   INKY_STUDIO_INSTALL_DIR install dir (default: /home/<user>/inky-studio)
#   INKY_STUDIO_DATA_DIR    data dir (default: /var/lib/inky-studio)
#   INKY_STUDIO_REPO_SLUG   GitHub slug (default: mehdi7129/inky-studio)
#   INKY_STUDIO_NO_REBOOT=1 don't auto-reboot even if one is required

set -euo pipefail

CHANNEL="${INKY_STUDIO_CHANNEL:-release}"
RUN_USER="${INKY_STUDIO_USER:-pi}"
INSTALL_DIR="${INKY_STUDIO_INSTALL_DIR:-/home/${RUN_USER}/inky-studio}"
DATA_DIR="${INKY_STUDIO_DATA_DIR:-/var/lib/inky-studio}"
REPO_SLUG="${INKY_STUDIO_REPO_SLUG:-mehdi7129/inky-studio}"
REPO_URL="${INKY_STUDIO_REPO:-https://github.com/${REPO_SLUG}.git}"
SERVICE_NAME="inky-studio.service"
LEGACY_SERVICE_NAME="inky-photo-frame.service"
BOOT_CONFIG="/boot/firmware/config.txt"
[[ -f "${BOOT_CONFIG}" ]] || BOOT_CONFIG="/boot/config.txt"

REBOOT_REQUIRED=0

if [[ "${EUID}" -eq 0 ]]; then
  echo "❌ Don't run this as root — run as the '${RUN_USER}' user. sudo is invoked when needed." >&2
  exit 1
fi

say() { printf '→ %s\n' "$*"; }

echo "════════════════════════════════════════════════════════════════"
echo "  Inky Studio installer"
echo "════════════════════════════════════════════════════════════════"
echo "  Channel     : ${CHANNEL}"
echo "  Install dir : ${INSTALL_DIR}"
echo "  Data dir    : ${DATA_DIR}"
echo "  Run as      : ${RUN_USER}"
echo "════════════════════════════════════════════════════════════════"
echo

# ── 1. System packages ───────────────────────────────────────────────────────
say "Installing system packages (apt)…"
sudo apt-get update -qq
# python3-dev + build-essential are required to compile the spidev / RPi.GPIO
# C extensions inside the venv — without them `pip install .[pi]` fails.
sudo apt-get install -y --no-install-recommends \
  git python3 python3-venv python3-pip python3-dev build-essential \
  fonts-dejavu fonts-dejavu-core \
  curl ca-certificates gnupg

# ── 2. Enable SPI + I2C ──────────────────────────────────────────────────────
if command -v raspi-config >/dev/null 2>&1; then
  if [[ ! -e /dev/spidev0.0 ]]; then
    say "Enabling SPI…"
    sudo raspi-config nonint do_spi 0 || true
    REBOOT_REQUIRED=1
  fi
  if [[ ! -e /dev/i2c-1 ]]; then
    say "Enabling I2C…"
    sudo raspi-config nonint do_i2c 0 || true
    REBOOT_REQUIRED=1
  fi
fi

# ── 3. Free GPIO8 for the Inky library (dtoverlay=spi0-0cs) ───────────────────
# Newer Inky displays drive the chip-select themselves; the kernel's spi0 CS0
# otherwise claims GPIO8 and the first refresh aborts with "pins in use".
if [[ -f "${BOOT_CONFIG}" ]] && ! grep -q '^dtoverlay=spi0-0cs' "${BOOT_CONFIG}"; then
  say "Adding dtoverlay=spi0-0cs to ${BOOT_CONFIG}…"
  sudo cp "${BOOT_CONFIG}" "${BOOT_CONFIG}.bak-inky" 2>/dev/null || true
  printf '\n# Inky Studio: SPI0 without hardware chip-select → frees GPIO8 for the Inky library\ndtoverlay=spi0-0cs\n' \
    | sudo tee -a "${BOOT_CONFIG}" >/dev/null
  REBOOT_REQUIRED=1
fi

# ── 4. Swap (low-RAM Pis) ────────────────────────────────────────────────────
MEM_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
SWAP_KB=$(awk '/SwapTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
if [[ "${MEM_KB}" -gt 0 && "${MEM_KB}" -lt 1048576 && "${SWAP_KB}" -lt 1048576 && ! -f /swapfile ]]; then
  say "Creating a 1 GB swap file (low RAM detected)…"
  sudo fallocate -l 1G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=1024
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile || true
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# ── 5. Disable the older v2.0 service if present ─────────────────────────────
if systemctl list-unit-files --type=service 2>/dev/null | grep -q "^${LEGACY_SERVICE_NAME}"; then
  say "Stopping & disabling legacy ${LEGACY_SERVICE_NAME}…"
  sudo systemctl stop "${LEGACY_SERVICE_NAME}" || true
  sudo systemctl disable "${LEGACY_SERVICE_NAME}" || true
  STRAYS=$(pgrep -f "inky-photo-frame/inky_photo_frame" || true)
  if [[ -n "${STRAYS}" ]]; then
    sudo kill -TERM ${STRAYS} 2>/dev/null || true
    sleep 2
    sudo kill -KILL $(pgrep -f "inky-photo-frame/inky_photo_frame" || true) 2>/dev/null || true
  fi
fi

# ── 6. Fetch the code ────────────────────────────────────────────────────────
fetch_release() {
  local api="https://api.github.com/repos/${REPO_SLUG}/releases/latest"
  local json asset tag tmp
  json=$(curl -fsSL -H "Accept: application/vnd.github+json" "${api}" 2>/dev/null || true)
  [[ -z "${json}" ]] && return 1
  asset=$(printf '%s' "${json}" | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
print(next((a["browser_download_url"] for a in d.get("assets",[]) if a.get("name","").endswith(".tar.gz")), ""))' 2>/dev/null || true)
  tag=$(printf '%s' "${json}" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("tag_name",""))
except Exception: pass' 2>/dev/null || true)
  [[ -z "${asset}" ]] && return 1

  say "Downloading release ${tag}…"
  tmp=$(mktemp -d)
  curl -fsSL -o "${tmp}/release.tar.gz" "${asset}"
  mkdir -p "${tmp}/x"
  tar -xzf "${tmp}/release.tar.gz" -C "${tmp}/x"
  local src="${tmp}/x"
  if [[ ! -d "${src}/server" ]]; then
    local inner
    inner=$(find "${tmp}/x" -mindepth 1 -maxdepth 1 -type d | head -1)
    [[ -d "${inner}/server" ]] && src="${inner}"
  fi
  [[ -d "${src}/server" ]] || { echo "❌ Release archive has no server/ — aborting." >&2; rm -rf "${tmp}"; return 1; }
  mkdir -p "${INSTALL_DIR}"
  # Copy over the install dir, leaving any existing .venv intact.
  cp -a "${src}/." "${INSTALL_DIR}/"
  rm -rf "${tmp}"
  echo "${tag}" > "${INSTALL_DIR}/VERSION" 2>/dev/null || true
  return 0
}

fetch_source() {
  # Build from main — needs Node 22 for the Vite build.
  local need_node=1
  if command -v node >/dev/null 2>&1; then
    [[ "$(node -v | sed -E 's/^v([0-9]+)\..*/\1/')" -ge 20 ]] && need_node=0
  fi
  if [[ "${need_node}" -eq 1 ]]; then
    say "Installing Node 22 (NodeSource)…"
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
  fi
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    say "Updating checkout in ${INSTALL_DIR}…"
    git -C "${INSTALL_DIR}" fetch --depth=1 origin main
    git -C "${INSTALL_DIR}" reset --hard origin/main
  else
    say "Cloning ${REPO_URL}…"
    mkdir -p "$(dirname "${INSTALL_DIR}")"
    git clone --depth=1 "${REPO_URL}" "${INSTALL_DIR}"
  fi
  say "Building the frontend (1-3 min on a Pi Zero)…"
  ( cd "${INSTALL_DIR}/client" && npm ci --no-audit --no-fund --no-progress && npm run build )
}

if [[ "${CHANNEL}" == "source" ]]; then
  fetch_source
else
  if ! fetch_release; then
    echo "⚠️  No prebuilt release found — falling back to building from source."
    fetch_source
  fi
fi

# ── 7. Python venv ───────────────────────────────────────────────────────────
say "Setting up the Python venv…"
cd "${INSTALL_DIR}/server"
[[ -d .venv ]] || python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -e ".[pi]"

# ── 8. Data directory ────────────────────────────────────────────────────────
say "Creating data directory ${DATA_DIR}…"
sudo install -d -m 0755 -o "${RUN_USER}" -g "${RUN_USER}" "${DATA_DIR}"
sudo install -d -m 0755 -o "${RUN_USER}" -g "${RUN_USER}" "${DATA_DIR}/photos"

# ── 9. Scoped sudo so the app can restart itself (one-click update) ───────────
say "Granting scoped sudo for service restart…"
SUDOERS_TMP=$(mktemp)
cat > "${SUDOERS_TMP}" <<EOF
# Inky Studio: let the service user (re)start ONLY its own service, so the
# in-app one-click update can restart cleanly without a password.
${RUN_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart ${SERVICE_NAME}, /usr/bin/systemctl stop ${SERVICE_NAME}, /usr/bin/systemctl start ${SERVICE_NAME}
EOF
sudo install -m 0440 -o root -g root "${SUDOERS_TMP}" /etc/sudoers.d/inky-studio
rm -f "${SUDOERS_TMP}"
sudo visudo -cf /etc/sudoers.d/inky-studio >/dev/null

# ── 10. CLI wrapper ──────────────────────────────────────────────────────────
say "Installing CLI at /usr/local/bin/inky-studio…"
sudo install -m 0755 "${INSTALL_DIR}/scripts/inky-studio-cli" /usr/local/bin/inky-studio

# ── 11. systemd unit ─────────────────────────────────────────────────────────
say "Writing systemd unit…"
sudo tee "/etc/systemd/system/${SERVICE_NAME}" >/dev/null <<EOF
[Unit]
Description=Inky Studio — Web UI for the Inky e-ink photo frame
Documentation=https://github.com/${REPO_SLUG}
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}/server
Environment="INKY_STUDIO_DATA_DIR=${DATA_DIR}"
Environment="INKY_STUDIO_REPO_SLUG=${REPO_SLUG}"
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
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  sudo systemctl restart "${SERVICE_NAME}"
else
  sudo systemctl start "${SERVICE_NAME}"
fi

# ── 12. Report ───────────────────────────────────────────────────────────────
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
echo "  CLI:       inky-studio help"
echo "════════════════════════════════════════════════════════════════"

# ── 13. Reboot if SPI/config changed (first install only) ─────────────────────
if [[ "${REBOOT_REQUIRED}" -eq 1 && "${INKY_STUDIO_NO_REBOOT:-0}" != "1" ]]; then
  echo
  echo "⚠️  A reboot is needed to finish enabling the display (SPI)."
  echo "    Rebooting in 10 s — press Ctrl-C to cancel (then run 'sudo reboot' yourself)."
  for i in $(seq 10 -1 1); do printf "\r    %2d…  " "${i}"; sleep 1; done
  echo
  sudo reboot
elif [[ "${REBOOT_REQUIRED}" -eq 1 ]]; then
  echo
  echo "⚠️  Reboot required to finish enabling the display:  sudo reboot"
fi
