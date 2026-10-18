#!/bin/sh
cd "$(dirname "$0")"
. ./ensure_python.sh
ensure_python || exit 1
exec python3 install.py "$@"
