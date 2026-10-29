#!/usr/bin/env bash
set -euo pipefail
umask 077
SUPPORT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PYTHON="${INKY_TLS_TEST_PYTHON:-$(command -v python3.13 || command -v python3)}"
exec "${PYTHON}" "${SUPPORT}/generate_fixtures.py"
