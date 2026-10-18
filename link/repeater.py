"""Repeat Civilization Revolution LAN discovery across the overlay.

The game broadcasts to UDP 26900-26996. WireGuard does not fan a broadcast
out to every peer, so the host watches the tunnel and sends each peer a
unicast copy that still uses the original console's overlay address.
"""

from __future__ import annotations

import select
import socket
import threading
import time
from collections.abc import Callable

from .common import DISCOVERY_FIRST, DISCOVERY_LAST, IFACE, LAN_IFACE, is_discovery_broadcast
from .packets import build_ipv4_udp, parse_ip_udp

ETH_P_ALL = 0x0003


class DiscoveryRepeater:
    def __init__(self, targets_for: Callable[[str], list[str]], ifaces: list[str] | None = None) -> None:
        self.targets_for = targets_for
        self.ifaces = ifaces or [LAN_IFACE, IFACE]
        self._stop = threading.Event()
        self._seen: dict[tuple[str, int, bytes], float] = {}
        self._send = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        self._send.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

    def stop(self) -> None:
        self._stop.set()

    def serve(self) -> None:
        while not self._stop.is_set():
            sockets = self._open()
            if not sockets:
                self._stop.wait(2)
                continue
            try:
                self._read(sockets)
            finally:
                for sniff in sockets:
                    sniff.close()

    def _open(self) -> list[socket.socket]:
        sockets: list[socket.socket] = []
        for iface in self.ifaces:
            try:
                sniff = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
                sniff.bind((iface, 0))
                sniff.settimeout(0.5)
            except OSError as exc:
                print(f"repeater waiting for {iface}: {exc}", flush=True)
                continue
            sockets.append(sniff)
        return sockets

    def _read(self, sockets: list[socket.socket]) -> None:
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select(sockets, [], [], 0.5)
            except OSError:
                print("repeater lost an overlay device", flush=True)
                return
            for sniff in readable:
                try:
                    frame = sniff.recv(65535)
                except TimeoutError:
                    continue
                except OSError:
                    print("repeater lost an overlay device", flush=True)
                    return
                self._forward(frame)

    def _forward(self, frame: bytes) -> None:
        parsed = parse_ip_udp(frame)
        if parsed is None:
            return
        src, dest, sport, dport, payload = parsed
        if not DISCOVERY_FIRST <= dport <= DISCOVERY_LAST:
            return
        if not is_discovery_broadcast(dest):
            return
        key = (src, dport, payload)
        now = time.monotonic()
        if now - self._seen.get(key, 0) < 0.2:
            return
        self._seen[key] = now
        self._forget_old(now)
        for target in self.targets_for(src):
            packet = build_ipv4_udp(src, target, sport, dport, payload)
            try:
                self._send.sendto(packet, (target, 0))
            except OSError as exc:
                print(f"repeater: {src} -> {target}:{dport} failed: {exc}", flush=True)

    def _forget_old(self, now: float) -> None:
        if len(self._seen) < 4096:
            return
        cutoff = now - 5
        self._seen = {key: seen for key, seen in self._seen.items() if seen >= cutoff}
