#!/usr/bin/env bash
# Run from a reviewed checkout/release, as root. No arbitrary sudo rule is added.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo 'Run this installer with sudo after reviewing the Bluetooth release.' >&2
  exit 1
fi
if [[ $# -ne 1 || ! $1 =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo 'Usage: install-bluetooth.sh <existing-app-service-user>' >&2
  exit 2
fi
APP_USER=$1
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
HELPER="${ROOT}/scripts/inky-network-helper.py"
id "${APP_USER}" >/dev/null
[[ -f ${HELPER} && ! -L ${HELPER} ]]
[[ -x /usr/bin/python3 && -d /etc/systemd/system ]]
/usr/bin/python3 -I -c 'import dbus'
systemctl is-active --quiet NetworkManager
SERVICE_USER=$(systemctl show inky-studio.service -p User --value)
if [[ ${SERVICE_USER} != "${APP_USER}" ]]; then
  echo 'The supplied user does not match inky-studio.service; no installation performed.' >&2
  exit 2
fi

getent group inky-provisioning >/dev/null || groupadd --system inky-provisioning
# The same account owns the app's code/data and its local recovery CLI. Give
# both the fixed helper protocol, never NetworkManager permissions directly.
usermod -aG inky-provisioning "${APP_USER}"
if ! id inky-network >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin \
    --gid inky-provisioning inky-network
fi
if [[ $(id -u inky-network) == 0 ]]; then
  echo 'Refusing a privileged helper account.' >&2
  exit 2
fi
install -d -m 0755 -o root -g root /usr/local/lib/inky-studio
install -m 0555 -o root -g root "${HELPER}" /usr/local/lib/inky-studio/network-helper.py
install -d -m 0755 -o root -g root /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/49-inky-network.rules <<'POLKIT'
polkit.addRule(function(action, subject) {
    if (subject.user !== "inky-network") return polkit.Result.NOT_HANDLED;
    var permitted = [
        "org.freedesktop.NetworkManager.wifi.scan",
        "org.freedesktop.NetworkManager.network-control",
        "org.freedesktop.NetworkManager.settings.modify.system",
        "org.freedesktop.NetworkManager.checkpoint-rollback"
    ];
    if (permitted.indexOf(action.id) !== -1) return polkit.Result.YES;
    return polkit.Result.NOT_HANDLED;
});
POLKIT
chmod 0644 /etc/polkit-1/rules.d/49-inky-network.rules
chown root:root /etc/polkit-1/rules.d/49-inky-network.rules
cat > /etc/systemd/system/inky-network.service <<'UNIT'
[Unit]
Description=Inky Studio limited Wi-Fi configuration helper
After=NetworkManager.service
Requires=NetworkManager.service

[Service]
Type=simple
User=inky-network
Group=inky-provisioning
ExecStart=/usr/bin/python3 -I /usr/local/lib/inky-studio/network-helper.py
RuntimeDirectory=inky-network
RuntimeDirectoryMode=0750
StateDirectory=inky-network
StateDirectoryMode=0700
UMask=0077
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=
LockPersonality=yes
MemoryDenyWriteExecute=yes

[Install]
WantedBy=multi-user.target
UNIT
install -d -m 0755 -o root -g root /etc/systemd/system/inky-studio.service.d
cat > /etc/systemd/system/inky-studio.service.d/bluetooth.conf <<'UNIT'
[Unit]
Wants=bluetooth.service inky-network.service
After=bluetooth.service inky-network.service

[Service]
SupplementaryGroups=inky-provisioning
Environment=INKY_STUDIO_BLUETOOTH=1
UNIT
systemctl daemon-reload
systemctl enable --now bluetooth.service
/usr/sbin/rfkill unblock bluetooth
busctl set-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered b true
systemctl enable --now inky-network.service
systemctl is-active --quiet inky-network.service
echo 'Bluetooth prerequisites installed. The application must be restarted with the qualified Bluetooth release.'
echo 'Reconnect SSH before using the local password recovery CLI (new supplementary group).'
echo 'No Wi-Fi profile has been changed by this installer.'
