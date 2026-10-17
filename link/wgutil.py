"""WireGuard config rendering. Encryption stays in WireGuard."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .common import HOST_IP, IFACE, NETWORK, PREFIX, WG_PORT


def wg_available() -> bool:
    from shutil import which

    return which("wg") is not None


def generate_keypair() -> tuple[str, str]:
    if not wg_available():
        raise SystemExit("wireguard-tools is not installed (the wg command is missing)")
    private = subprocess.check_output(["wg", "genkey"], text=True).strip()
    public = subprocess.check_output(["wg", "pubkey"], input=private + "\n", text=True).strip()
    return private, public


def server_config(private_key: str, peers: list[tuple[str, str]]) -> str:
    lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {HOST_IP}/{PREFIX}",
        f"ListenPort = {WG_PORT}",
        "",
    ]
    for public_key, ip in peers:
        lines.extend(
            [
                "[Peer]",
                f"PublicKey = {public_key}",
                f"AllowedIPs = {ip}/32",
                "",
            ]
        )
    return "\n".join(lines)


def client_config(private_key: str, address: str, server_public_key: str, endpoint: str) -> str:
    return "\n".join(
        [
            "[Interface]",
            f"PrivateKey = {private_key}",
            f"Address = {address}/32",
            "",
            "[Peer]",
            f"PublicKey = {server_public_key}",
            f"Endpoint = {endpoint}",
            f"AllowedIPs = {NETWORK}",
            "PersistentKeepalive = 25",
            "",
        ]
    )


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def interface_name() -> str:
    return IFACE
