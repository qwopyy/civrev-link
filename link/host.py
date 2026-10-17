"""Host process: WireGuard peer list plus the discovery repeater."""

from __future__ import annotations

import argparse
import socket
import subprocess
import threading
import urllib.request
from pathlib import Path

from .common import IFACE, WG_PORT, fanout_targets, hash_passphrase, host_state_dir
from .introducer import Introducer
from .repeater import DiscoveryRepeater
from .state import HostState
from .wgutil import generate_keypair, server_config, write_private

UNIT_PATH = Path("/etc/systemd/system/civrev-link.service")
WG_CONFIG = Path("/etc/wireguard/civrev.conf")


def main() -> None:
    parser = argparse.ArgumentParser(description="Civilization Revolution link host")
    parser.add_argument("--run", action="store_true", help="run the introducer and repeater")
    args = parser.parse_args()
    if args.run:
        run()
    else:
        parser.error("use install.py --host to set the host up")


def run() -> None:
    state_path = host_state_dir() / "state.json"
    state = HostState.load(state_path)
    introducer = Introducer(state, state_path, WG_CONFIG)

    def targets(source: str) -> list[str]:
        with introducer._lock:
            return fanout_targets(source, state.peer_ips())

    repeater = DiscoveryRepeater(targets)
    threading.Thread(target=repeater.serve, daemon=True).start()
    introducer.serve()


def bootstrap(passphrase: str, endpoint_host: str, repo_root: Path) -> HostState:
    directory = host_state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "state.json"
    if state_path.exists():
        state = HostState.load(state_path)
        state.endpoint_host = endpoint_host
        salt, digest = hash_passphrase(passphrase)
        state.passphrase_salt = salt
        state.passphrase_hash = digest
    else:
        private, public = generate_keypair()
        salt, digest = hash_passphrase(passphrase)
        cert_pem, key_pem = _certificate(directory)
        state = HostState(
            passphrase_salt=salt,
            passphrase_hash=digest,
            server_private_key=private,
            server_public_key=public,
            cert_pem=cert_pem,
            key_pem=key_pem,
            endpoint_host=endpoint_host,
        )
    state.save(state_path)
    write_private(
        WG_CONFIG,
        server_config(state.server_private_key, [(peer.public_key, peer.ip) for peer in state.peers]),
    )
    _sysctl_forward()
    subprocess.run(["wg-quick", "down", IFACE], check=False, capture_output=True)
    subprocess.check_call(["wg-quick", "up", IFACE])
    subprocess.run(["sysctl", "-w", f"net.ipv4.conf.{IFACE}.rp_filter=0"], check=False)
    subprocess.run(["systemctl", "enable", f"wg-quick@{IFACE}"], check=False)
    _install_unit(repo_root)
    subprocess.check_call(["systemctl", "daemon-reload"])
    subprocess.check_call(["systemctl", "enable", "--now", "civrev-link.service"])
    return state


def lan_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("1.1.1.1", 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


def public_ip() -> str:
    with urllib.request.urlopen("https://api.ipify.org", timeout=8) as response:
        return response.read().decode().strip()


def _certificate(directory: Path) -> tuple[str, str]:
    cert = directory / "cert.pem"
    key = directory / "key.pem"
    subprocess.check_call(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "3650",
            "-nodes",
            "-subj",
            "/CN=civrev-link",
        ]
    )
    key.chmod(0o600)
    return cert.read_text(encoding="utf-8"), key.read_text(encoding="utf-8")


def _sysctl_forward() -> None:
    path = Path("/etc/sysctl.d/99-civrev-link.conf")
    path.write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
    subprocess.run(["sysctl", "--system"], check=False, capture_output=True)


def _install_unit(repo_root: Path) -> None:
    python = "/usr/bin/python3"
    UNIT_PATH.write_text(
        "\n".join(
            [
                "[Unit]",
                "Description=Civilization Revolution player link",
                "After=network-online.target wg-quick@civrev.service",
                "Wants=network-online.target wg-quick@civrev.service",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={repo_root}",
                f"ExecStart={python} -m link.host --run",
                "Restart=on-failure",
                "RestartSec=2",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
