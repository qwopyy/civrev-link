"""Shared constants and small helpers. No game files live here."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sys
from pathlib import Path

WG_PORT = 51820
CTRL_PORT = 51821
NETWORK = "10.66.0.0/24"
HOST_IP = "10.66.0.1"
PREFIX = 24
IFACE = "civrev"
DISCOVERY_FIRST = 26900
DISCOVERY_LAST = 26996
TITLE_IDS = ("BLUS30130", "BLES00238")
MAX_PEERS = 8

LINUX_RELEASE_API = "https://api.github.com/repos/RPCS3/rpcs3-binaries-linux/releases/latest"
WINDOWS_RELEASE_API = "https://api.github.com/repos/RPCS3/rpcs3-binaries-win/releases/latest"

# links
FIRMWARE_URL = "https://www.dropbox.com/scl/fi/iqzlv8gcpoahe87w3fj5z/PS3UPDAT.PUP?rlkey=rslrhn37heukheelwe3hw4be1&st=mf0ysl8n&dl=1"
GAME_URL = "https://www.dropbox.com/scl/fi/k6m9avybwxc6i24xj102g/Sid-Meier-s-Civilization-Revolution-USA-En-Fr-De-Es-It.iso?rlkey=oo1z5okmhooj97g3v22ct9yi3&st=tebab053&dl=1"

REPO_ROOT = Path(__file__).resolve().parent.parent


def is_windows() -> bool:
    return sys.platform == "win32"


def config_home() -> Path:
    if is_windows():
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "civrev-link"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "civrev-link"


def host_state_dir() -> Path:
    return Path("/var/lib/civrev-link")


def rpcs3_config_dirs(install_dir: Path) -> list[Path]:
    """Directories where RPCS3 looks for config/custom_configs/."""
    dirs = [install_dir]
    if is_windows():
        appdata = os.environ.get("APPDATA")
        if appdata:
            dirs.append(Path(appdata) / "rpcs3")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        dirs.append(base / "rpcs3")
    unique: list[Path] = []
    for path in dirs:
        if path not in unique:
            unique.append(path)
    return unique


def hash_passphrase(passphrase: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return salt.hex(), digest.hex()


def passphrase_matches(passphrase: str, salt_hex: str, digest_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), digest_hex)


def clean_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", name.strip())[:32].strip("-")
    return cleaned or "player"


def overlay_ip(index: int) -> str:
    """index 0 is the host. Players start at 1."""
    if not 0 <= index <= 254:
        raise ValueError(f"overlay index out of range: {index}")
    return f"10.66.0.{index}"


def is_discovery_broadcast(dest_ip: str) -> bool:
    return dest_ip in {"10.66.0.255", "255.255.255.255"}


def fanout_targets(source_ip: str, peer_ips: list[str]) -> list[str]:
    """Overlay addresses that should receive a unicast copy of a discovery packet."""
    targets = [ip for ip in peer_ips if ip != source_ip]
    if source_ip != HOST_IP and HOST_IP not in targets:
        targets.append(HOST_IP)
    return targets
