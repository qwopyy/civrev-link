"""Tests for the link protocol and discovery packets. No game data."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from link.client import join_room
from link.common import fanout_targets, hash_passphrase, passphrase_matches
from link.introducer import Introducer
from link.packets import build_ipv4_udp, parse_ip_udp
from link.rpcs3 import _game_yaml
from link.state import HostState
from link.wgutil import client_config, server_config


class PacketTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        packet = build_ipv4_udp("10.66.0.2", "10.66.0.255", 40000, 26910, b"lobby")
        parsed = parse_ip_udp(packet)
        self.assertIsNotNone(parsed)
        src, dest, sport, dport, payload = parsed
        self.assertEqual((src, dest, sport, dport, payload), ("10.66.0.2", "10.66.0.255", 40000, 26910, b"lobby"))

    def test_ethernet_frame(self) -> None:
        packet = build_ipv4_udp("10.66.0.3", "255.255.255.255", 1, 26900, b"x")
        frame = b"\x00" * 12 + b"\x08\x00" + packet
        parsed = parse_ip_udp(frame)
        self.assertEqual(parsed[0], "10.66.0.3")
        self.assertEqual(parsed[3], 26900)


class RoomTests(unittest.TestCase):
    def test_passphrase(self) -> None:
        salt, digest = hash_passphrase("correct horse")
        self.assertTrue(passphrase_matches("correct horse", salt, digest))
        self.assertFalse(passphrase_matches("wrong", salt, digest))

    def test_fanout_skips_sender(self) -> None:
        targets = fanout_targets("10.66.0.2", ["10.66.0.2", "10.66.0.3"])
        self.assertEqual(targets, ["10.66.0.3", "10.66.0.1"])

    def test_configs_do_not_route_the_whole_internet(self) -> None:
        server = server_config("priv", [("pub", "10.66.0.2")])
        client = client_config("priv", "10.66.0.2", "pub", "203.0.113.5:51820")
        self.assertIn("AllowedIPs = 10.66.0.2/32", server)
        self.assertIn("AllowedIPs = 10.66.0.0/24", client)
        self.assertNotIn("0.0.0.0/0", client)

    def test_game_yaml_binds_the_overlay(self) -> None:
        text = _game_yaml("10.66.0.4")
        self.assertIn("Internet enabled: Connected", text)
        self.assertIn("PSN status: Disconnected", text)
        self.assertIn("Bind address: 10.66.0.4", text)
        self.assertIn("Silence All Logs: true", text)


class IntroducerTests(unittest.TestCase):
    def test_join_assigns_an_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            cert, key = _certificate(directory)
            salt, digest = hash_passphrase("room-secret")
            state = HostState(
                passphrase_salt=salt,
                passphrase_hash=digest,
                server_private_key="c" * 44,
                server_public_key="s" * 44,
                cert_pem=cert,
                key_pem=key,
                endpoint_host="203.0.113.9",
            )
            state_path = directory / "state.json"
            wg_config = directory / "civrev.conf"
            introducer = Introducer(state, state_path, wg_config)
            port = _free_port()
            thread = threading.Thread(target=introducer.serve, kwargs={"host": "127.0.0.1", "port": port}, daemon=True)
            thread.start()
            deadline = __import__("time").monotonic() + 5
            reply = None
            while __import__("time").monotonic() < deadline:
                try:
                    reply = join_room("127.0.0.1", "room-secret", "p" * 44, "c" * 44, "alex", None, port=port)
                    break
                except (ConnectionRefusedError, TimeoutError, OSError):
                    __import__("time").sleep(0.05)
            self.assertIsNotNone(reply)
            self.assertTrue(reply["ok"])
            self.assertEqual(reply["ip"], "10.66.0.2")
            self.assertEqual(reply["endpoint"], "203.0.113.9:51820")
            again = join_room("127.0.0.1", "room-secret", "p" * 44, "c" * 44, "alex", reply["fingerprint"], port=port)
            self.assertEqual(again["ip"], "10.66.0.2")
            with self.assertRaises(SystemExit):
                join_room("127.0.0.1", "nope", "p" * 44, "d" * 44, "alex", reply["fingerprint"], port=port)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


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
            "2",
            "-nodes",
            "-subj",
            "/CN=civrev-test",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.chmod(key, 0o600)
    return cert.read_text(encoding="utf-8"), key.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
