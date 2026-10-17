"""IPv4/UDP helpers for repeating Civilization Revolution discovery broadcasts."""

from __future__ import annotations

import struct


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


def parse_ip_udp(frame: bytes) -> tuple[str, str, int, int, bytes] | None:
    """Return src, dest, sport, dport, payload. Accepts a bare IPv4 packet or an Ethernet frame."""
    start = 0
    if len(frame) >= 14 and (frame[0] >> 4) != 4:
        ethertype = struct.unpack("!H", frame[12:14])[0]
        if ethertype != 0x0800:
            return None
        start = 14
    if len(frame) < start + 20:
        return None
    version = frame[start] >> 4
    if version != 4:
        return None
    header_len = (frame[start] & 0x0F) * 4
    if header_len < 20 or len(frame) < start + header_len + 8:
        return None
    protocol = frame[start + 9]
    if protocol != 17:
        return None
    src = ".".join(str(b) for b in frame[start + 12:start + 16])
    dest = ".".join(str(b) for b in frame[start + 16:start + 20])
    udp_off = start + header_len
    sport, dport, length = struct.unpack("!HHH", frame[udp_off:udp_off + 6])
    payload = frame[udp_off + 8:udp_off + length] if length >= 8 else frame[udp_off + 8:]
    return src, dest, sport, dport, payload


def build_ipv4_udp(src: str, dest: str, sport: int, dport: int, payload: bytes) -> bytes:
    """IPv4 UDP packet with a zero UDP checksum. IP_HDRINCL sockets can send this."""
    src_b = bytes(int(part) for part in src.split("."))
    dest_b = bytes(int(part) for part in dest.split("."))
    udp_len = 8 + len(payload)
    udp = struct.pack("!HHHH", sport, dport, udp_len, 0) + payload
    total = 20 + len(udp)
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        total,
        0,
        0,
        64,
        17,
        0,
        src_b,
        dest_b,
    )
    header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
    return header + udp
