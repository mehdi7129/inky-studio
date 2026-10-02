#!/usr/bin/env bash
# Build and qualify the same prebuilt payload in PR CI and release CI.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 VERSION OUTPUT.tar.gz" >&2
  exit 2
fi

version="$1"
output="$2"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$(dirname "$output")"
output="$(cd "$(dirname "$output")" && pwd)/$(basename "$output")"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/inky-release.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
stage="$work_dir/staging"
archive="$work_dir/release.tar.gz"
cd "$root"

mkdir -p "$stage/client"
rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '*.egg-info' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '.mypy_cache' \
  --exclude '.DS_Store' \
  --exclude 'tests' \
  server "$stage/"
cp -a client/dist "$stage/client/dist"
rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
  shared scripts "$stage/"
cp install.sh README.md LICENSE CHANGELOG.md "$stage/"
printf '%s\n' "$version" > "$stage/VERSION"

# Updater contract: ustar regular files/directories; no PAX/GNU extensions.
# Disable macOS AppleDouble metadata when qualifying locally with bsdtar.
COPYFILE_DISABLE=1 tar --format=ustar -czf "$archive" -C "$stage" .
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/server" python3 - "$archive" "$work_dir/extracted" <<'PY'
import runpy
import sys
from pathlib import Path

# Load the stdlib-only updater directly: the services package __init__ imports
# the web application's dependencies, which packaging does not need.
updater = runpy.run_path("server/inky_web/services/updater.py")

archive, extracted = map(Path, sys.argv[1:])
if archive.stat().st_size > updater["_MAX_DOWNLOAD_BYTES"]:
    raise SystemExit("Release archive exceeds the updater download limit")
updater["_safe_extract"](archive, extracted)
updater["_validate_payload"](extracted)
print(f"Qualified release payload: {archive.stat().st_size} compressed bytes")
PY
mv "$archive" "$output"
printf 'Archive: %s\n' "$output"
