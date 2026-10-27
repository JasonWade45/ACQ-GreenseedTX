#!/usr/bin/env bash
# Update an existing installation from this extracted release folder.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f scripts/update_acq.py ]; then
    echo "This file must stay inside the extracted release folder." >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.11 or newer is required, but python3 was not found." >&2
    exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "Python 3.11 or newer is required. Found: $(python3 -V 2>&1)" >&2
    exit 1
fi

echo
echo "This updates your existing installation and keeps your data, password and settings."
echo "Stop the app first if it is still running."
echo
exec python3 scripts/update_acq.py --start "$@"
