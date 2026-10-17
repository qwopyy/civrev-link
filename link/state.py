"""Persistent host and player records. Secrets stay mode 0600."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .common import HOST_IP, overlay_ip


@dataclass
class Peer:
    name: str
    public_key: str
    ip: str

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "public_key": self.public_key, "ip": self.ip}

    @classmethod
    def from_json(cls, raw: dict[str, str]) -> "Peer":
        return cls(name=raw["name"], public_key=raw["public_key"], ip=raw["ip"])


@dataclass
class HostState:
    passphrase_salt: str
    passphrase_hash: str
    server_private_key: str
    server_public_key: str
    cert_pem: str
    key_pem: str
    endpoint_host: str
    peers: list[Peer] = field(default_factory=list)

    def peer_ips(self) -> list[str]:
        return [peer.ip for peer in self.peers]

    def next_ip(self) -> str:
        used = {peer.ip for peer in self.peers}
        used.add(HOST_IP)
        for index in range(2, 255):
            candidate = overlay_ip(index)
            if candidate not in used:
                return candidate
        raise RuntimeError("no overlay addresses left")

    def upsert(self, name: str, public_key: str) -> Peer:
        for peer in self.peers:
            if peer.public_key == public_key:
                peer.name = name
                return peer
        peer = Peer(name=name, public_key=public_key, ip=self.next_ip())
        self.peers.append(peer)
        return peer

    def to_json(self) -> dict:
        return {
            "passphrase_salt": self.passphrase_salt,
            "passphrase_hash": self.passphrase_hash,
            "server_private_key": self.server_private_key,
            "server_public_key": self.server_public_key,
            "cert_pem": self.cert_pem,
            "key_pem": self.key_pem,
            "endpoint_host": self.endpoint_host,
            "peers": [peer.to_json() for peer in self.peers],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        os.chmod(path, 0o600)

    @classmethod
    def load(cls, path: Path) -> "HostState":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            passphrase_salt=raw["passphrase_salt"],
            passphrase_hash=raw["passphrase_hash"],
            server_private_key=raw["server_private_key"],
            server_public_key=raw["server_public_key"],
            cert_pem=raw["cert_pem"],
            key_pem=raw["key_pem"],
            endpoint_host=raw["endpoint_host"],
            peers=[Peer.from_json(item) for item in raw.get("peers", [])],
        )
