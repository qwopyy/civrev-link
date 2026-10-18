#!/bin/sh
# Install Python 3.11 or newer when the player does not already have it.

ensure_python() {
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        return 0
    fi
    echo "Installing Python 3. This asks for your password."
    if command -v pacman >/dev/null 2>&1; then
        _as_root pacman -S --needed --noconfirm python
    elif command -v apt-get >/dev/null 2>&1; then
        _as_root apt-get update
        _as_root apt-get install -y python3
    elif command -v dnf >/dev/null 2>&1; then
        _as_root dnf install -y python3
    else
        echo "Install Python 3.11 or newer, then run this again."
        return 1
    fi
    if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        echo "Python is still older than 3.11. Install a newer Python, then run this again."
        return 1
    fi
}

_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}
