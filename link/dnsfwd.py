"""Answer overlay DNS lookups from the host's normal internet connection.

RPCS3 binds the game to its overlay address. A lookup from that address to a
public resolver never gets an answer, and Civilization Revolution treats that
as losing the network.
"""

from __future__ import annotations

import socket
import threading

UPSTREAM = "8.8.8.8"


class DnsForwarder:
    def __init__(self, listen: str, upstream: str = UPSTREAM) -> None:
        self.listen = listen
        self.upstream = upstream
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def serve(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.listen, 53))
        sock.settimeout(0.5)
        print(f"dns forwarder listening on udp {self.listen}:53", flush=True)
        while not self._stop.is_set():
            try:
                query, addr = sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError as exc:
                print(f"dns forwarder stopped: {exc}", flush=True)
                return
            try:
                reply = _forward(query, self.upstream)
            except OSError:
                continue
            try:
                sock.sendto(reply, addr)
            except OSError:
                continue


def _forward(query: bytes, upstream: str) -> bytes:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    try:
        sock.sendto(query, (upstream, 53))
        reply, _addr = sock.recvfrom(4096)
        return reply
    finally:
        sock.close()
