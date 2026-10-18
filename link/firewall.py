"""Open the ports the link and the game use. Existing drop rules still win."""

from __future__ import annotations

import shutil
import subprocess

from .common import CTRL_PORT, DISCOVERY_FIRST, DISCOVERY_LAST, WG_PORT, as_root, is_windows


def open_ports() -> None:
    if is_windows():
        _windows()
    else:
        _linux()


def _linux() -> None:
    if shutil.which("ufw") and _ufw_active():
        for spec in (f"{WG_PORT}/udp", f"{CTRL_PORT}/tcp", f"{DISCOVERY_FIRST}:{DISCOVERY_LAST}/udp"):
            subprocess.run(as_root(["ufw", "allow", spec]), check=False)
        return
    if shutil.which("nft"):
        subprocess.run(as_root(["nft", "delete", "table", "ip", "civrev"]), check=False, capture_output=True)
        script = f"""
add table ip civrev
add chain ip civrev input {{ type filter hook input priority 0; policy accept; }}
add rule ip civrev input udp dport {WG_PORT} accept
add rule ip civrev input tcp dport {CTRL_PORT} accept
add rule ip civrev input udp dport {DISCOVERY_FIRST}-{DISCOVERY_LAST} accept
add chain ip civrev forward {{ type filter hook forward priority 0; policy accept; }}
add rule ip civrev forward iifname "civrev" oifname "civrev" accept
"""
        subprocess.run(as_root(["nft", "-f", "-"]), input=script, text=True, check=False)
    if shutil.which("iptables"):
        for args in (
            ["-C", "FORWARD", "-i", "civrev", "-o", "civrev", "-j", "ACCEPT"],
            ["-A", "FORWARD", "-i", "civrev", "-o", "civrev", "-j", "ACCEPT"],
        ):
            if args[0] == "-A":
                probe = subprocess.run(as_root(["iptables", "-C", "FORWARD", "-i", "civrev", "-o", "civrev", "-j", "ACCEPT"]), check=False)
                if probe.returncode == 0:
                    continue
            subprocess.run(as_root(["iptables", *args]), check=False)


def _ufw_active() -> bool:
    result = subprocess.run(as_root(["ufw", "status"]), capture_output=True, text=True, check=False)
    return "Status: active" in result.stdout


def windows_commands() -> list[list[str]]:
    program = "rpcs3.exe"
    specs = [
        ["advfirewall", "firewall", "add", "rule", "name=civrev-wg", "dir=in", "action=allow", "protocol=udp", f"localport={WG_PORT}"],
        ["advfirewall", "firewall", "add", "rule", "name=civrev-introducer", "dir=in", "action=allow", "protocol=tcp", f"localport={CTRL_PORT}"],
        ["advfirewall", "firewall", "add", "rule", "name=civrev-discovery", "dir=in", "action=allow", "protocol=udp", f"localport={DISCOVERY_FIRST}-{DISCOVERY_LAST}", f"program={program}"],
    ]
    return [["netsh", *spec] for spec in specs]


def _windows() -> None:
    from .windows import run_admin_batch

    print("Opening the game ports. Windows may ask for administrator approval.", flush=True)
    run_admin_batch(windows_commands(), required=0)
