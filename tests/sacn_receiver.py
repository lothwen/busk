"""An independent E1.31 data packet parser and a localhost receiver, for the tests.

The parser imports nothing from :mod:`busk.output.sacn`. It reads every field
at its own offsets, transcribed from the E1.31 data packet table (ANSI
E1.31-2018 Table 4-1; phase-1.5-plan §3), and checks every field whose value
the standard fixes. A layout mistake in the production code therefore fails
here instead of round-tripping through shared constants.

:class:`Receiver` is a UDP socket bound to an ephemeral localhost port. Tests
point sACN routes at it by monkeypatching ``busk.output.sacn.SACN_PORT``
(the ``receiver`` fixture in ``conftest.py`` does both), so no packet ever
leaves the machine.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import uuid
from dataclasses import dataclass
from types import TracebackType
from typing import Self

HEADER = struct.Struct(
    "!"  # network byte order, no padding
    "H"  # 0    preamble size
    "H"  # 2    post-amble size
    "12s"  # 4    ACN packet identifier
    "H"  # 16   root layer flags & length
    "I"  # 18   root layer vector
    "16s"  # 22   CID
    "H"  # 38   framing layer flags & length
    "I"  # 40   framing layer vector
    "64s"  # 44   source name
    "B"  # 108  priority
    "H"  # 109  synchronization address
    "B"  # 111  sequence number
    "B"  # 112  options
    "H"  # 113  universe
    "H"  # 115  DMP layer flags & length
    "B"  # 117  DMP vector
    "B"  # 118  address type & data type
    "H"  # 119  first property address
    "H"  # 121  address increment
    "H"  # 123  property value count
    "B"  # 125  START code
)
"""Everything before the DMX slots, which start at offset 126."""

STREAM_TERMINATED = 0x40
"""Options bit 6 (E1.31 §6.2.6)."""


@dataclass(frozen=True, kw_only=True)
class DataPacket:
    """The variable fields of a parsed E1.31 data packet."""

    cid: uuid.UUID
    sourceName: str
    priority: int
    syncAddress: int
    sequence: int
    options: int
    universe: int
    startCode: int
    data: bytes  # the DMX slots after the START code

    @property
    def terminated(self) -> bool:
        return bool(self.options & STREAM_TERMINATED)


def parse(packet: bytes) -> DataPacket:
    """Parse an E1.31 data packet.

    Raises :class:`ValueError` naming the first field that breaks the
    standard: a wrong fixed value, a PDU length that doesn't match the
    packet's size, or a source name that isn't NUL-terminated and NUL-padded.
    """
    if len(packet) <= HEADER.size:
        raise ValueError(f"packet of {len(packet)} bytes is too short")
    (
        preamble,
        postamble,
        identifier,
        root,
        root_vector,
        cid,
        framing,
        framing_vector,
        name,
        priority,
        sync_address,
        sequence,
        options,
        universe,
        dmp,
        dmp_vector,
        address_type,
        first_address,
        increment,
        count,
        start_code,
    ) = HEADER.unpack_from(packet)
    size = len(packet)
    text, _, padding = name.partition(b"\0")
    expected: dict[str, tuple[object, object]] = {
        # field: (actual, expected); PDU lengths run from the PDU's flags to the packet's end.
        "preamble size": (preamble, 0x0010),
        "post-amble size": (postamble, 0x0000),
        "ACN packet identifier": (identifier, b"ASC-E1.17\0\0\0"),
        "root flags & length": (root, 0x7000 | (size - 16)),
        "root vector": (root_vector, 0x00000004),  # VECTOR_ROOT_E131_DATA
        "framing flags & length": (framing, 0x7000 | (size - 38)),
        "framing vector": (framing_vector, 0x00000002),  # VECTOR_E131_DATA_PACKET
        "source name terminator": (len(text) < 64, True),
        "source name padding": (padding, bytes(len(padding))),
        "DMP flags & length": (dmp, 0x7000 | (size - 115)),
        "DMP vector": (dmp_vector, 0x02),  # VECTOR_DMP_SET_PROPERTY
        "address & data type": (address_type, 0xA1),
        "first property address": (first_address, 0x0000),
        "address increment": (increment, 0x0001),
        "property value count": (count, size - 125),  # START code + slots
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError(f"{field}: {actual!r}, expected {wanted!r}")
    return DataPacket(
        cid=uuid.UUID(bytes=cid),
        sourceName=text.decode("utf-8"),
        priority=priority,
        syncAddress=sync_address,
        sequence=sequence,
        options=options,
        universe=universe,
        startCode=start_code,
        data=bytes(packet[HEADER.size :]),
    )


class Receiver:
    """Collects E1.31 packets sent to a UDP port; parses each one on arrival."""

    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock

    @classmethod
    def localhost(cls) -> Self:
        """A receiver on ``127.0.0.1`` and an ephemeral port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        return cls(sock)

    @classmethod
    def multicast(cls, group: str, iface: str) -> Self:
        """A receiver on an ephemeral port that joined ``group`` on interface ``iface``
        (a name: the membership uses a Linux ``struct ip_mreqn``)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", 0))
        membership = struct.pack(
            "=4s4si",
            ipaddress.IPv4Address(group).packed,  # imr_multiaddr
            bytes(4),  # imr_address: any
            socket.if_nametoindex(iface),  # imr_ifindex
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        return cls(sock)

    @property
    def port(self) -> int:
        port: int = self._socket.getsockname()[1]
        return port

    def receive(self, timeout: float = 2.0) -> DataPacket:
        """The next packet; :class:`TimeoutError` if none arrives in ``timeout`` seconds."""
        self._socket.settimeout(timeout)
        return parse(self._socket.recv(2048))

    def drain(self, quiet: float = 0.2) -> list[DataPacket]:
        """Every packet that arrives until none has arrived for ``quiet`` seconds."""
        packets: list[DataPacket] = []
        while True:
            try:
                packets.append(self.receive(quiet))
            except TimeoutError:
                return packets

    def discard(self) -> int:
        """Drop every packet already queued, without waiting or parsing; return
        how many there were."""
        self._socket.setblocking(False)
        count = 0
        while True:
            try:
                self._socket.recv(2048)
            except BlockingIOError:
                return count
            count += 1

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
