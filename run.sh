#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -x .venv/bin/python ]]; then
    PYTHON=.venv/bin/python
else
    PYTHON="${PYTHON:-python3}"
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
    printf '%s\n' "CDFlow requires Python 3.12 or newer." >&2
    exit 1
fi

if ! "$PYTHON" -c 'import cdflow' >/dev/null 2>&1; then
    export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
fi

exec "$PYTHON" -m cdflow "$@"

