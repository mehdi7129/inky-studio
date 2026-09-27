#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${INKY_HTTPS_PYTHON:-}" ]; then
    PYTHON="$INKY_HTTPS_PYTHON"
elif [ -x /opt/homebrew/bin/python3.13 ]; then
    PYTHON=/opt/homebrew/bin/python3.13
else
    PYTHON=python3
fi
exec "$PYTHON" "$SCRIPT_DIR/https-wire-bench/run.py" "$@"
