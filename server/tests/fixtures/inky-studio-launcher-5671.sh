#!/usr/bin/env bash
# Generate or install the stable launcher. Application updates replace only
# scripts/inky-studio-cli; the root-owned launcher contains no command logic.
set -euo pipefail

usage() {
  echo "Usage: $0 --print|--install INSTALL_DIR DATA_DIR" >&2
}

if [[ $# -ne 3 ]]; then
  usage
  exit 2
fi

mode="$1"
launcher_install_dir="$2"
launcher_data_dir="$3"
if [[ "${mode}" != "--print" && "${mode}" != "--install" ]]; then
  usage
  exit 2
fi
if [[ "${launcher_install_dir}" != /* || "${launcher_data_dir}" != /* ]]; then
  echo "Inky Studio: INSTALL_DIR and DATA_DIR must be absolute paths." >&2
  exit 2
fi

render_launcher() {
  cat <<'HEADER'
#!/usr/bin/env bash
# Inky Studio stable launcher: application updates replace the delegated script.
# Run as the normal service user; privileged service commands use scoped sudo.
set -euo pipefail
HEADER
  # %q quotes literal Bash values, including spaces, quotes, $, ` and newlines.
  # Never substitute paths into executable shell text with sed or eval.
  printf 'INKY_DEFAULT_INSTALL_DIR=%q\n' "${launcher_install_dir}"
  printf 'INKY_DEFAULT_DATA_DIR=%q\n' "${launcher_data_dir}"
  cat <<'BODY'
export INKY_STUDIO_INSTALL_DIR="${INKY_STUDIO_INSTALL_DIR:-${INKY_DEFAULT_INSTALL_DIR}}"
export INKY_STUDIO_DATA_DIR="${INKY_STUDIO_DATA_DIR:-${INKY_DEFAULT_DATA_DIR}}"
inky_cli="${INKY_STUDIO_INSTALL_DIR}/scripts/inky-studio-cli"
if [[ ! -f "${inky_cli}" || ! -r "${inky_cli}" ]]; then
  printf 'Inky Studio: command script missing or unreadable: %s\n' "${inky_cli}" >&2
  echo 'Restore the installation or correct INKY_STUDIO_INSTALL_DIR. No service was changed.' >&2
  exit 127
fi
exec /bin/bash -- "${inky_cli}" "$@"
BODY
}

if [[ "${mode}" == "--print" ]]; then
  render_launcher
  exit 0
fi

if [[ ! -f "${launcher_install_dir}/scripts/inky-studio-cli" || ! -r "${launcher_install_dir}/scripts/inky-studio-cli" ]]; then
  echo "Inky Studio: scripts/inky-studio-cli must exist in INSTALL_DIR before installing the launcher." >&2
  exit 1
fi
launcher_tmp=$(mktemp)
trap 'rm -f "${launcher_tmp}"' EXIT
render_launcher > "${launcher_tmp}"
/bin/bash -n "${launcher_tmp}"
sudo install -o root -g root -m 0755 "${launcher_tmp}" /usr/local/bin/inky-studio
echo "Installed stable Inky Studio launcher at /usr/local/bin/inky-studio."
