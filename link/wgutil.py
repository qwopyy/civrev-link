"""WireGuard config rendering. Encryption stays in WireGuard."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .common import HOST_IP, IFACE, NETWORK, PREFIX, WG_PORT, is_windows


def wg_available() -> bool:
    return wg_binary() is not None


def wg_binary() -> str | None:
    """The wg tool. The Windows app installs it beside wireguard.exe and does not add it to PATH."""
    found = shutil.which("wg")
    if found:
        return found
    if not is_windows():
        return None
    return first_existing([Path(root) / "WireGuard" / "wg.exe" for root in _program_roots()])


def wireguard_app() -> str | None:
    if not is_windows():
        return None
    return first_existing([Path(root) / "WireGuard" / "wireguard.exe" for root in _program_roots()])


def _program_roots() -> list[str]:
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
    return [root for root in roots if root]


def first_existing(candidates: list[Path]) -> str | None:
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def generate_keypair() -> tuple[str, str]:
    binary = wg_binary()
    if binary is None:
        raise SystemExit("wireguard-tools is not installed (the wg command is missing)")
    private = subprocess.check_output([binary, "genkey"], text=True).strip()
    public = subprocess.check_output([binary, "pubkey"], input=private + "\n", text=True).strip()
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
