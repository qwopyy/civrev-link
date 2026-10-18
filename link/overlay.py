"""Give the WireGuard overlay a normal LAN device.

WireGuard rejects a broadcast with "Required key not available". Civilization
Revolution sends those broadcasts to open a LAN game, and treats the failure
as a lost network connection.
"""

from __future__ import annotations

import shutil
import subprocess

from .common import HOST_IP, IFACE, LAN_IFACE, PREFIX


def ensure_lan(peer_ips: list[str]) -> str:
    subprocess.run(["ip", "link", "add", LAN_IFACE, "type", "dummy"], check=False, capture_output=True)
    subprocess.run(["ip", "addr", "del", f"{HOST_IP}/{PREFIX}", "dev", IFACE], check=False, capture_output=True)
    subprocess.run(["ip", "addr", "replace", f"{HOST_IP}/{PREFIX}", "dev", LAN_IFACE], check=False)
    subprocess.run(["ip", "link", "set", LAN_IFACE, "up"], check=False)
    for address in peer_ips:
        subprocess.run(
            ["ip", "route", "replace", f"{address}/32", "dev", IFACE, "src", HOST_IP],
            check=False,
        )
    for name in (IFACE, LAN_IFACE):
        subprocess.run(["sysctl", "-w", f"net.ipv4.conf.{name}.rp_filter=0"], check=False, capture_output=True)
    if shutil.which("ufw"):
        for name in (IFACE, LAN_IFACE):
            subprocess.run(["ufw", "allow", "in", "on", name], check=False, capture_output=True)
    return LAN_IFACE
