#!/usr/bin/env python3
"""Bring the link up, then start RPCS3 on the game image chosen during install."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from link.client import load_player
from link.common import HOST_IP, IFACE, config_home
from link.rpcs3 import control_summary, write_game_config
from link.wgutil import wireguard_app


def main() -> None:
    record = load_player()
    binary = Path(record["rpcs3"])
    game = Path(record["game"])
    if not binary.exists():
        raise SystemExit(f"RPCS3 is missing at {binary}. Run the installer again.")
    if not game.exists():
        raise SystemExit(f"Game image is missing at {game}.")
    address = _overlay_address(record)
    write_game_config(binary.parent, address)
    if record.get("role") != "host":
        _ensure_tunnel()
    print(f"Starting RPCS3 as {address}.", flush=True)
    print(control_summary(), flush=True)
    print("Host from Multiplayer, then LAN Party. Wait to press Ready until the others have joined.", flush=True)
    _start_game(binary, game)


def _overlay_address(record: dict) -> str:
    if record.get("role") == "host":
        return HOST_IP
    shown = _interface_address()
    return shown or record["ip"]


def _interface_address() -> str | None:
    if sys.platform == "win32":
        return None
    result = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", IFACE], capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            return parts[parts.index("inet") + 1].split("/")[0]
    return None


def _start_game(binary: Path, game: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen([str(binary), str(game)], cwd=str(binary.parent))
        return
    os.execv(str(binary), [str(binary), str(game)])


def _ensure_tunnel() -> None:
    if _interface_address():
        return
    conf = config_home() / "civrev.conf"
    if not conf.exists():
        raise SystemExit("The tunnel config is missing. Run the installer again.")
    if sys.platform == "win32":
        _ensure_windows_tunnel(conf)
        return
    subprocess.check_call(["sudo", "install", "-m", "600", str(conf), "/etc/wireguard/civrev.conf"])
    subprocess.check_call(["sudo", "wg-quick", "up", "civrev"])


def _ensure_windows_tunnel(conf: Path) -> None:
    from link.windows import run_admin_batch, tunnel_action, tunnel_service_name, tunnel_state

    action = tunnel_action(tunnel_state(conf))
    if action == "skip":
        return
    exe = wireguard_app()
    if exe is None:
        raise SystemExit("WireGuard is missing. Run the installer again.")
    if action == "start":
        print("Starting the tunnel. Approve the administrator prompt.", flush=True)
        run_admin_batch([["sc", "start", tunnel_service_name(conf)]], required=1)
        return
    print("Connecting the tunnel. Approve the administrator prompt.", flush=True)
    run_admin_batch([[exe, "/installtunnelservice", str(conf)]], required=1)


if __name__ == "__main__":
    main()
