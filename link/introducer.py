"""TLS introducer. Friends present the room passphrase and receive an overlay address."""

from __future__ import annotations

import json
import socket
import ssl
import threading
from pathlib import Path

from .common import CTRL_PORT, MAX_PEERS, WG_PORT, clean_name, passphrase_matches
from .state import HostState
from .wgutil import server_config, write_private

MAX_MESSAGE = 4096


class Introducer:
    def __init__(self, state: HostState, state_path: Path, wg_config: Path) -> None:
        self.state = state
        self.state_path = state_path
        self.wg_config = wg_config
        self._lock = threading.Lock()

    def serve(self, host: str = "0.0.0.0", port: int = CTRL_PORT) -> None:
        _write_pem(Path(self._pem("cert")), self.state.cert_pem)
        _write_pem(Path(self._pem("key")), self.state.key_pem)
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(8)
        server.settimeout(0.5)
        print(f"introducer listening on tcp {host}:{port}", flush=True)
        while True:
            try:
                client, address = server.accept()
            except TimeoutError:
                continue
            threading.Thread(target=self._handle, args=(client, address), daemon=True).start()

    def _handle(self, client: socket.socket, address: tuple) -> None:
        tls = None
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=self._pem("cert"), keyfile=self._pem("key"))
            tls = context.wrap_socket(client, server_side=True)
            raw = _readline(tls)
            message = json.loads(raw)
            if message.get("op") != "join":
                _send(tls, {"ok": False, "error": "unknown op"})
                return
            passphrase = str(message.get("passphrase", ""))
            public_key = str(message.get("public_key", "")).strip()
            name = clean_name(str(message.get("name", "player")))
            if not passphrase_matches(passphrase, self.state.passphrase_salt, self.state.passphrase_hash):
                _send(tls, {"ok": False, "error": "bad passphrase"})
                return
            if len(public_key) < 40:
                _send(tls, {"ok": False, "error": "missing wireguard public key"})
                return
            with self._lock:
                known = any(peer.public_key == public_key for peer in self.state.peers)
                if not known and len(self.state.peers) >= MAX_PEERS:
                    _send(tls, {"ok": False, "error": "room is full"})
                    return
                peer = self.state.upsert(name, public_key)
                self.state.save(self.state_path)
                self._sync_wireguard()
            _send(
                tls,
                {
                    "ok": True,
                    "ip": peer.ip,
                    "server_public_key": self.state.server_public_key,
                    "endpoint": f"{self.state.endpoint_host}:{WG_PORT}",
                },
            )
            print(f"joined {peer.name} as {peer.ip} from {address[0]}", flush=True)
        except (OSError, json.JSONDecodeError, ssl.SSLError, UnicodeError, ValueError) as exc:
            print(f"introducer rejected {address[0]}: {exc}", flush=True)
        finally:
            try:
                if tls is not None:
                    tls.close()
                else:
                    client.close()
            except OSError:
                pass

    def _sync_wireguard(self) -> None:
        text = server_config(
            self.state.server_private_key,
            [(peer.public_key, peer.ip) for peer in self.state.peers],
        )
        write_private(self.wg_config, text)
        _wg_sync(self.state)


    def _pem(self, kind: str) -> str:
        return str(self.state_path.parent / f"{kind}.pem")


def _write_pem(path: Path, pem: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != pem:
        write_private(path, pem)


def _readline(tls: ssl.SSLSocket) -> str:
    data = b""
    while b"\n" not in data:
        chunk = tls.recv(1024)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_MESSAGE:
            raise ValueError("message too large")
    return data.decode("utf-8").strip()


def _send(tls: ssl.SSLSocket, payload: dict) -> None:
    tls.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def _wg_sync(state: HostState) -> None:
    import subprocess

    from .common import IFACE

    for peer in state.peers:
        try:
            subprocess.run(
                ["wg", "set", IFACE, "peer", peer.public_key, "allowed-ips", f"{peer.ip}/32"],
                check=False,
            )
        except FileNotFoundError:
            return
