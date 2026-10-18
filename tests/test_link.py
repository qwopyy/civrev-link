"""Tests for the link protocol and discovery packets. No game data."""

from __future__ import annotations

import ast
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
from link.python_setup import windows_installer_url
from link.common import as_root, desktop_session_env, fanout_targets, hash_passphrase, passphrase_matches
from link.introducer import Introducer
from link.packets import build_ipv4_udp, parse_ip_udp
from link.rpcs3 import _game_yaml, _keyboard_yaml, _write_configs, download_linked_file, filename_from_url
from link.state import HostState
from link.wgutil import client_config, first_existing, server_config
from link.windows import admin_batch, latest_msi_name, msiexec_install_args, wireguard_arch


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

    def test_filename_from_url(self) -> None:
        self.assertEqual(filename_from_url("https://example.test/files/PS3UPDAT.PUP?token=1"), "PS3UPDAT.PUP")
        with self.assertRaises(SystemExit):
            filename_from_url("https://example.test/")

    def test_linked_file_keeps_the_url_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "game.iso"
            source.write_bytes(b"image")
            downloaded = download_linked_file(source.as_uri(), directory / "out")
            self.assertEqual(downloaded.name, "game.iso")
            self.assertEqual(downloaded.read_bytes(), b"image")
            again = download_linked_file(source.as_uri(), directory / "out")
            self.assertEqual(again, downloaded)

    def test_game_yaml_binds_the_overlay(self) -> None:
        text = _game_yaml("10.66.0.4")
        self.assertIn("Internet enabled: Connected", text)
        self.assertIn("PSN status: Disconnected", text)
        self.assertIn("Bind address: 10.66.0.4", text)
        self.assertIn("Silence All Logs: true", text)
        self.assertIn('Mouse: "Null"', text)

    def test_keyboard_profile_maps_the_mouse_to_the_left_stick(self) -> None:
        text = _keyboard_yaml()
        self.assertIn("Handler: Keyboard", text)
        self.assertIn("Device: Keyboard", text)
        self.assertIn("Left Stick Up: Mouse MUp", text)
        self.assertIn("Cross: Mouse Left", text)
        self.assertIn("Circle: Mouse Right,Esc", text)
        self.assertIn("Mouse Movement Mode: Relative", text)
        with tempfile.TemporaryDirectory() as tmp:
            written = _write_configs([Path(tmp)], "10.66.0.4")
            names = {path.name for path in written}
            self.assertIn("config_BLUS30130.yml", names)
            self.assertIn("Default.yml", names)
            pad = Path(tmp) / "config" / "input_configs" / "BLES00238" / "Default.yml"
            self.assertEqual(pad.read_text(encoding="utf-8"), text)

    def test_package_install_escalates_only_the_command(self) -> None:
        command = as_root(["pacman", "-S", "--needed", "--noconfirm", "wireguard-tools"])
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.assertEqual(command, ["pacman", "-S", "--needed", "--noconfirm", "wireguard-tools"])
        else:
            self.assertEqual(command, ["sudo", "pacman", "-S", "--needed", "--noconfirm", "wireguard-tools"])

    def test_sudo_session_gets_the_wayland_socket_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            home = root / "home"
            runtime.mkdir()
            home.mkdir()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(runtime / "wayland-1"))
            (runtime / "wayland-1.lock").write_text("", encoding="utf-8")
            (runtime / "bus").touch()
            try:
                env = desktop_session_env(
                    {"SUDO_USER": "qwopy", "SUDO_UID": "1000", "DISPLAY": ":0", "PATH": "/usr/bin"},
                    "qwopy",
                    home,
                    runtime,
                )
            finally:
                sock.close()
            self.assertEqual(env["HOME"], str(home))
            self.assertEqual(env["USER"], "qwopy")
            self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-1")
            self.assertEqual(env["XDG_RUNTIME_DIR"], str(runtime))
            self.assertEqual(env["DISPLAY"], ":0")
            self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], f"unix:path={runtime / 'bus'}")
            self.assertNotIn("SUDO_USER", env)
            self.assertNotIn("SUDO_UID", env)

    def test_installer_does_not_import_pwd_at_startup(self) -> None:
        tree = ast.parse((Path(__file__).resolve().parent.parent / "install.py").read_text(encoding="utf-8"))
        imported = [alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names]
        self.assertNotIn("pwd", imported)

    def test_windows_wireguard_is_found_beside_the_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "WireGuard" / "wg.exe"
            exe.parent.mkdir()
            exe.write_bytes(b"")
            missing = Path(tmp) / "missing" / "wg.exe"
            self.assertEqual(first_existing([missing, exe]), str(exe))
            self.assertIsNone(first_existing([missing]))

    def test_windows_installer_picks_the_newest_official_msi(self) -> None:
        page = "\n".join(
            [
                "wireguard-amd64-1.0.0.msi",
                "wireguard-amd64-1.10.0.msi",
                "wireguard-amd64-1.9.2.msi",
                "wireguard-arm64-1.11.0.msi",
            ]
        )
        self.assertEqual(latest_msi_name(page, "amd64"), "wireguard-amd64-1.10.0.msi")
        self.assertEqual(wireguard_arch("AMD64"), "amd64")
        self.assertEqual(wireguard_arch("ARM64"), "arm64")
        with self.assertRaises(SystemExit):
            wireguard_arch("mips")
        args = msiexec_install_args(Path(r"C:\Downloads\wireguard-amd64-1.10.0.msi"))
        self.assertEqual(args[:2], ["msiexec", "/i"])
        self.assertEqual(args[-2:], ["/qn", "DO_NOT_LAUNCH=1"])

    def test_tunnel_failure_is_not_hidden_by_later_firewall_rules(self) -> None:
        script = admin_batch(
            [
                [r"C:\Program Files\WireGuard\wireguard.exe", "/installtunnelservice", r"C:\room files\civrev.conf"],
                ["netsh", "advfirewall", "firewall", "add", "rule"],
            ],
            required=1,
        )
        lines = [line for line in script.splitlines() if line]
        self.assertEqual(lines[0], "@echo off")
        self.assertIn(r"C:\Program Files\WireGuard\wireguard.exe", lines[1])
        self.assertIn(r"C:\room files\civrev.conf", lines[1])
        self.assertEqual(lines[2], "if errorlevel 1 exit /b %errorlevel%")
        self.assertTrue(lines[3].startswith("netsh "))
        self.assertEqual(lines[4], "exit /b 0")
        self.assertEqual(script.count("if errorlevel 1"), 1)

    def test_windows_python_installer_uses_a_published_exe(self) -> None:
        page = "\n".join(
            [
                '<a href="/downloads/release/python-3160a1/">Python 3.16.0a1</a>',
                "https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.exe",
                "https://www.python.org/ftp/python/3.15.0/python-3.15.0-amd64.exe",
                "https://www.python.org/ftp/python/3.15.0/python-3.15.0-arm64.exe",
                "https://www.python.org/ftp/python/3.15.0/python-3.15.0.exe",
                "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe",
            ]
        )
        self.assertEqual(
            windows_installer_url(page, "AMD64"),
            "https://www.python.org/ftp/python/3.15.0/python-3.15.0-amd64.exe",
        )
        self.assertEqual(
            windows_installer_url(page, "ARM64"),
            "https://www.python.org/ftp/python/3.15.0/python-3.15.0-arm64.exe",
        )
        self.assertEqual(
            windows_installer_url(page, "x86"),
            "https://www.python.org/ftp/python/3.15.0/python-3.15.0.exe",
        )
        with self.assertRaises(SystemExit):
            windows_installer_url("Python 3.16.0a1", "AMD64")


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
