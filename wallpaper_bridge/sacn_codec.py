"""
Minimal ANSI E1.31 (streaming ACN / sACN) packet codec.

Used by the bridge's sACN-output emitter (v1.5: parallel to the
OpenRGB-output channel — reaches xLights / QLC+ / Hyperion / any
lighting controller that subscribes to a multicast universe) and
the sACN-input source manager (lets users drive the wallpaper glow
from any sACN sender on their network).

Spec reference: ANSI E1.31-2018. We implement the DATA_PACKET
(VECTOR_E131_DATA_PACKET) only — discovery / synchronisation
packets are not relevant to a single-screen colour-mirror flow.

A complete E1.31 DATA packet is 126 + slot_count bytes:
  • 38-byte Root Layer (preamble + ACN ident + flags + vector + CID)
  • 77-byte Framing Layer (flags + vector + source name + priority +
    sync addr + sequence + options + universe)
  • 11-byte DMP Layer header (flags + vector + addr type + first
    addr + increment + property value count)
  • 1-byte DMX start code (0x00) + N DMX slots (1 ≤ N ≤ 512)

This module deliberately stays free of bridge imports so it can be
reused by ad-hoc test scripts.
"""

from __future__ import annotations

import socket
import struct
import uuid


# ─── constants ────────────────────────────────────────────────────────────

E131_PORT             = 5568
ACN_PACKET_IDENTIFIER = b"ASC-E1.17\x00\x00\x00"
ROOT_VECTOR_DATA      = 0x00000004
FRAMING_VECTOR_DATA   = 0x00000002
DMP_VECTOR            = 0x02
DMP_ADDR_DATA_TYPE    = 0xa1
DEFAULT_PRIORITY      = 100

# Length minimums per spec (header sizes when slot_count = 1)
# We compute exact lengths per-packet — these are illustrative.

# Public CID for the bridge. Per spec, each E1.31 source SHOULD pick
# a stable UUID so receivers can keep per-source state across reboots.
# We derive ours deterministically from a fixed namespace + product
# name so subsequent restarts re-use the same CID without persisting
# anything to disk.
BRIDGE_CID = uuid.uuid5(uuid.NAMESPACE_DNS,
                        "signalrgb-wallpaper.bridge.e131").bytes


# ─── multicast addressing ────────────────────────────────────────────────

def multicast_group_for(universe: int) -> str:
    """Per ANSI E1.31 sec. 9.3.1: multicast destination is
    239.255.X.Y where (X << 8) | Y == universe. Universe 0 is
    reserved (not legal on the wire); 1..63999 are user space."""
    if universe < 1 or universe > 63999:
        raise ValueError(f"universe {universe} out of range [1, 63999]")
    return f"239.255.{(universe >> 8) & 0xff}.{universe & 0xff}"


# ─── pack ────────────────────────────────────────────────────────────────

def pack_e131(universe: int,
              dmx_data: bytes,
              *,
              source_name: str = "SignalRGB Wallpaper Bridge",
              sequence: int = 0,
              priority: int = DEFAULT_PRIORITY,
              cid: bytes = BRIDGE_CID,
              options: int = 0,
              sync_address: int = 0,
              stream_terminated: bool = False) -> bytes:
    """Build a single E1.31 DATA_PACKET. `dmx_data` is the raw DMX
    slot payload (1-512 bytes); we prepend the mandatory 0x00 start
    code automatically. `sequence` rolls over modulo 256 — callers
    typically increment a per-universe counter."""
    if not 1 <= len(dmx_data) <= 512:
        raise ValueError(f"dmx_data length {len(dmx_data)} out of range [1, 512]")
    if len(cid) != 16:
        raise ValueError("cid must be 16 bytes")

    # Pad / truncate source name to 64 bytes, null-terminated.
    name = source_name.encode("utf-8")[:63] + b"\x00"
    name = name.ljust(64, b"\x00")

    # Slot count includes the DMX start code byte (0x00).
    slot_count = len(dmx_data) + 1

    # Layer lengths (count this layer + everything after it).
    dmp_length     = 11 + slot_count
    framing_length = 77 + dmp_length
    root_length    = 22 + framing_length    # 22 bytes from flags-len onwards

    # Flag bits 0xfff = length, top nibble 0x7 = "PDU is non-extended".
    def _flags_len(n: int) -> int:
        return (0x7 << 12) | (n & 0x0fff)

    opt_byte = options & 0xff
    if stream_terminated:
        opt_byte |= 0x40

    pkt = bytearray()

    # ── Root Layer ─────────────────────────────────────────────
    pkt += struct.pack(">HH", 0x0010, 0x0000)        # preamble + postamble size
    pkt += ACN_PACKET_IDENTIFIER                     # 12 bytes
    pkt += struct.pack(">H", _flags_len(root_length))
    pkt += struct.pack(">I", ROOT_VECTOR_DATA)
    pkt += cid                                       # 16 bytes

    # ── Framing Layer ─────────────────────────────────────────
    pkt += struct.pack(">H", _flags_len(framing_length))
    pkt += struct.pack(">I", FRAMING_VECTOR_DATA)
    pkt += name
    pkt += struct.pack(">B", max(0, min(200, priority)))
    pkt += struct.pack(">H", sync_address & 0xffff)
    pkt += struct.pack(">B", sequence & 0xff)
    pkt += struct.pack(">B", opt_byte)
    pkt += struct.pack(">H", universe & 0xffff)

    # ── DMP Layer ─────────────────────────────────────────────
    pkt += struct.pack(">H", _flags_len(dmp_length))
    pkt += struct.pack(">B", DMP_VECTOR)
    pkt += struct.pack(">B", DMP_ADDR_DATA_TYPE)
    pkt += struct.pack(">H", 0x0000)                 # first property addr
    pkt += struct.pack(">H", 0x0001)                 # address increment
    pkt += struct.pack(">H", slot_count)             # property value count
    pkt += b"\x00"                                   # DMX start code
    pkt += dmx_data

    return bytes(pkt)


# ─── parse ───────────────────────────────────────────────────────────────

def parse_e131(packet: bytes) -> dict | None:
    """Parse an inbound E1.31 DATA_PACKET. Returns None on any layer
    mismatch (foreign protocol, sync packet, truncated, …). The
    returned dict has: universe, sequence, priority, source_name,
    dmx (bytes — slot data, start-code stripped)."""
    if len(packet) < 126:
        return None
    if packet[0:2] != b"\x00\x10" or packet[2:4] != b"\x00\x00":
        return None
    if packet[4:16] != ACN_PACKET_IDENTIFIER:
        return None
    # Root vector check.
    root_vector = struct.unpack_from(">I", packet, 18)[0]
    if root_vector != ROOT_VECTOR_DATA:
        return None
    # Framing layer starts at offset 38.
    framing_vector = struct.unpack_from(">I", packet, 40)[0]
    if framing_vector != FRAMING_VECTOR_DATA:
        return None
    source_name = packet[44:108].rstrip(b"\x00").decode("utf-8", "replace")
    priority    = packet[108]
    sequence    = packet[111]
    universe    = struct.unpack_from(">H", packet, 113)[0]
    # DMP layer starts at offset 115.
    dmp_vector = packet[117]
    if dmp_vector != DMP_VECTOR:
        return None
    addr_type = packet[118]
    if addr_type != DMP_ADDR_DATA_TYPE:
        return None
    slot_count = struct.unpack_from(">H", packet, 123)[0]
    if slot_count < 1 or 125 + slot_count > len(packet):
        return None
    # Start code at 125, DMX slots at 126..(126+slot_count-1).
    start_code = packet[125]
    if start_code != 0x00:
        # Non-zero start codes are out-of-band data (RDM, etc.); ignore.
        return None
    dmx = bytes(packet[126:126 + slot_count - 1])
    return {
        "universe":    universe,
        "sequence":    sequence,
        "priority":    priority,
        "source_name": source_name,
        "dmx":         dmx,
    }


# ─── socket helpers ──────────────────────────────────────────────────────

def make_multicast_sender_socket() -> socket.socket:
    """UDP socket pre-configured for E1.31 multicast TX. TTL=1 keeps
    packets on the local LAN — that's the conformant default for
    sACN unless the receiver explicitly subscribes via a higher TTL
    setup, which is rare for hobby lighting."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL,
                 struct.pack("b", 1))
    # SO_REUSEADDR so the bridge + another sender on the same host
    # don't bounce off each other.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return s


def join_multicast_group(sock: socket.socket, group: str,
                          iface: str = "0.0.0.0") -> None:
    """Add `sock` to multicast `group`. Caller is responsible for
    having opened the socket with bind(('', E131_PORT)) and
    SO_REUSEADDR first."""
    mreq = socket.inet_aton(group) + socket.inet_aton(iface)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
