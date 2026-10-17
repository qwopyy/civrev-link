#!/usr/bin/env python3
"""Install official RPCS3 and join the private Civilization Revolution link."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from link.client import apply_tunnel, join_room, save_player, write_client_tunnel
from link.common import REPO_ROOT, config_home, is_windows
from link.firewall import open_ports
from link.host import WG_PORT, bootstrap, lan_ip, public_ip
from link.rpcs3 import download_rpcs3, install_firmware, write_game_config
from link.wgutil import generate_keypair, wg_available


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up RPCS3 and the shared LAN Party link")
    parser.add_argument("--host", action="store_true", help="run the introducer on this machine")
    parser.add_argument("--endpoint", help="public address friends use to reach the host")
    parser.add_argument("--passphrase", help="room passphrase")
    parser.add_argument("--generate-passphrase", action="store_true", help="create a room passphrase and print it")
    parser.add_argument("--fingerprint", help="sha256 of the host certificate")
    parser.add_argument("--firmware", help="path to a PS3 firmware .pup you downloaded from Sony")
    parser.add_argument("--game", help="path to your own game image or dumped game folder")
    args = parser.parse_args()
    if args.host:
        become_host(args)
    else:
        become_player(args)


def become_host(args: argparse.Namespace) -> None:
    if not is_windows() and hasattr(os, "geteuid") and os.geteuid() != 0:
        os.execvp("sudo", ["sudo", sys.executable, *sys.argv])
    ensure_wireguard()
    passphrase = args.passphrase or _generated_or_prompt(args.generate_passphrase)
    endpoint = args.endpoint or _detect_public_ip()
    state = bootstrap(passphrase, endpoint, REPO_ROOT)
    open_ports()
    fingerprint = _pem_fingerprint(state.cert_pem)
    passphrase_path = Path("/var/lib/civrev-link/passphrase.txt")
    passphrase_path.write_text(passphrase + "\n", encoding="utf-8")
    passphrase_path.chmod(0o600)
    local = lan_ip()
    print()
    print("The link host is running.")
    print(f"Room passphrase: {passphrase}")
    print(f"Saved for you at {passphrase_path}")
    print(f"Public endpoint: {endpoint}")
    print(f"Certificate fingerprint: {fingerprint}")
    print(f"Forward UDP {WG_PORT} and TCP 51821 to {local}")
    print("Friends clone this repository, run the installer, and enter that endpoint, passphrase, and fingerprint.")
    print("Each person supplies their own PS3 firmware and their own game image. This repository does not contain either.")


def become_player(args: argparse.Namespace) -> None:
    install_dir = REPO_ROOT / "rpcs3"
    binary = download_rpcs3(install_dir)
    firmware = ask_path("PS3 firmware .pup from Sony", args.firmware)
    print("Installing firmware into RPCS3.", flush=True)
    install_firmware(binary, firmware)
    game = ask_path("your own game image or game folder", args.game, directory_ok=True)
    if _is_host_machine():
        _finish_host_player(binary, game)
        return
    ensure_wireguard()
    endpoint = args.endpoint or input("Host public address: ").strip()
    passphrase = args.passphrase or getpass.getpass("Room passphrase: ")
    fingerprint = args.fingerprint
    if fingerprint is None:
        fingerprint = input("Host certificate fingerprint (blank to accept this one): ").strip() or None
    private, public = generate_keypair()
    reply = join_room(endpoint, passphrase, private, public, socket.gethostname(), fingerprint)
    record = {
        "private_key": private,
        "public_key": public,
        "ip": reply["ip"],
        "server_public_key": reply["server_public_key"],
        "endpoint": reply["endpoint"],
        "fingerprint": reply["fingerprint"],
        "game": str(game),
        "rpcs3": str(binary),
    }
    save_player(record)
    conf = write_client_tunnel(record)
    apply_tunnel(conf)
    written = write_game_config(binary.parent, reply["ip"])
    open_ports()
    print()
    print(f"Joined as {reply['ip']}.")
    print(f"RPCS3 config written for both Civilization Revolution editions ({len(written)} files).")
    print("Start a session with ./play.sh or play.cmd.")
    print("One person opens Multiplayer, then LAN Party, and waits to press Ready until everyone has joined.")


def _finish_host_player(binary: Path, game: Path) -> None:
    from link.common import HOST_IP

    record = {
        "ip": HOST_IP,
        "game": str(game),
        "rpcs3": str(binary),
        "role": "host",
    }
    path = config_home() / "player.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    write_game_config(binary.parent, HOST_IP)
    print()
    print("This machine is the link host, so RPCS3 uses 10.66.0.1 and does not open a second tunnel.")
    print("Start a session with ./play.sh.")


def _is_host_machine() -> bool:
    return Path("/var/lib/civrev-link/state.json").exists()


def ensure_wireguard() -> None:
    if wg_available():
        return
    if is_windows():
        raise SystemExit("Install WireGuard for Windows from https://www.wireguard.com/install/ and run the installer again.")
    if _command_exists("pacman"):
        subprocess.check_call(["pacman", "-S", "--needed", "--noconfirm", "wireguard-tools"])
    elif _command_exists("apt-get"):
        subprocess.check_call(["apt-get", "update"])
        subprocess.check_call(["apt-get", "install", "-y", "wireguard"])
    if not wg_available():
        raise SystemExit("Install wireguard-tools, then run the installer again.")


def ask_path(label: str, given: str | None, directory_ok: bool = False) -> Path:
    if given:
        path = Path(given).expanduser()
        if not path.exists():
            raise SystemExit(f"not found: {path}")
        return path
    chosen = _dialog(label, directory_ok)
    if chosen:
        return chosen
    typed = input(f"Path to {label}: ").strip()
    path = Path(typed).expanduser()
    if not path.exists():
        raise SystemExit(f"not found: {path}")
    return path


def _dialog(label: str, directory_ok: bool) -> Path | None:
    try:
        import tkinter
        from tkinter import filedialog
    except Exception:
        return None
    root = tkinter.Tk()
    root.withdraw()
    if directory_ok:
        chosen = filedialog.askopenfilename(title=label) or filedialog.askdirectory(title=label)
    else:
        chosen = filedialog.askopenfilename(title=label, filetypes=[("PS3 firmware", "*.pup"), ("All files", "*.*")])
    root.destroy()
    return Path(chosen) if chosen else None


def _generated_or_prompt(generate: bool) -> str:
    if generate:
        import secrets

        return secrets.token_urlsafe(12)
    first = getpass.getpass("New room passphrase: ")
    second = getpass.getpass("Repeat room passphrase: ")
    if not first or first != second:
        raise SystemExit("The passphrases did not match.")
    return first


def _detect_public_ip() -> str:
    try:
        return public_ip()
    except OSError:
        return input("Public address friends can reach: ").strip()


def _pem_fingerprint(cert_pem: str) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
        handle.write(cert_pem)
        name = handle.name
    try:
        der = subprocess.check_output(["openssl", "x509", "-in", name, "-outform", "der"])
    finally:
        os.unlink(name)
    return hashlib.sha256(der).hexdigest()


def _command_exists(name: str) -> bool:
    from shutil import which

    return which(name) is not None


if __name__ == "__main__":
    main()
