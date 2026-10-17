"""Join the room and bring the local WireGuard interface up."""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
from pathlib import Path

from .common import CTRL_PORT, config_home, is_windows
from .wgutil import client_config, write_private

PLAYER_FILE = "player.json"


def join_room(
    endpoint_host: str,
    passphrase: str,
    private_key: str,
    public_key: str,
    name: str,
    fingerprint: str | None,
    port: int = CTRL_PORT,
) -> dict:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((endpoint_host, port), timeout=15)
    tls = context.wrap_socket(raw, server_hostname=endpoint_host)
    peer_fingerprint = _fingerprint(tls)
    if fingerprint and peer_fingerprint != fingerprint:
        tls.close()
        raise SystemExit("The host certificate does not match the fingerprint you were given.")
    message = {
        "op": "join",
        "passphrase": passphrase,
        "public_key": public_key,
        "name": name,
    }
    tls.sendall((json.dumps(message) + "\n").encode("utf-8"))
    reply = json.loads(_readline(tls))
    tls.close()
    if not reply.get("ok"):
        raise SystemExit(f"join failed: {reply.get('error', 'unknown error')}")
    reply["fingerprint"] = peer_fingerprint
    return reply


def save_player(record: dict) -> Path:
    path = config_home() / PLAYER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def load_player() -> dict:
    path = config_home() / PLAYER_FILE
    if not path.exists():
        raise SystemExit("This machine has not joined a room yet. Run the installer first.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_client_tunnel(record: dict) -> Path:
    text = client_config(
        record["private_key"],
        record["ip"],
        record["server_public_key"],
        record["endpoint"],
    )
    path = config_home() / "civrev.conf"
    write_private(path, text)
    return path


def apply_tunnel(conf: Path) -> None:
    if is_windows():
        exe = Path(r"C:\Program Files\WireGuard\wireguard.exe")
        if not exe.exists():
            raise SystemExit("Install WireGuard for Windows from https://www.wireguard.com/install/ and run the installer again.")
        subprocess.check_call([str(exe), "/installtunnelservice", str(conf)])
        return
    subprocess.run(["sudo", "wg-quick", "down", "civrev"], check=False, capture_output=True)
    subprocess.check_call(["sudo", "install", "-m", "600", str(conf), "/etc/wireguard/civrev.conf"])
    subprocess.check_call(["sudo", "wg-quick", "up", "civrev"])


def _fingerprint(tls: ssl.SSLSocket) -> str:
    import hashlib

    der = tls.getpeercert(binary_form=True)
    if der is None:
        raise SystemExit("the host did not present a certificate")
    return hashlib.sha256(der).hexdigest()


def _readline(tls: ssl.SSLSocket) -> str:
    data = b""
    while b"\n" not in data:
        chunk = tls.recv(1024)
        if not chunk:
            break
        data += chunk
    return data.decode("utf-8").strip()
