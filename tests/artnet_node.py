"""Independent Art-Net packet code, a localhost receiver and a fake node,
for the tests.

Nothing here imports from :mod:`busk.output.artnet`. The parsers and
builders read and write every field at their own offsets, transcribed from
the Art-Net 4 specification ("ArtDmx", "ArtPoll" and "ArtPollReply packet
definition"), and check every field whose value the specification fixes. A
layout mistake in the production code therefore fails here instead of
round-tripping through shared constants.

:class:`ArtNetReceiver` is a UDP socket bound to an ephemeral localhost port.
Tests point Art-Net routes at it by monkeypatching
``busk.output.artnet.ARTNET_PORT`` (the ``artnet_receiver`` fixture of
``conftest.py`` does both), so no packet ever leaves the machine.
:class:`FakeNode` answers ArtPolls with an ArtPollReply and records the
ArtDmx it receives.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from types import TracebackType
from typing import Self

DMX_HEADER = struct.Struct(
    "<"  # no padding; each multi-byte field below names its byte order
    "8s"  # 0   ID "Art-Net\0"
    "H"  # 8   OpCode, low byte first
    "2s"  # 10  ProtVerHi, ProtVerLo
    "B"  # 12  Sequence
    "B"  # 13  Physical
    "B"  # 14  SubUni: Sub-Net (high nibble), Universe (low nibble)
    "B"  # 15  Net: the Port-Address's top 7 bits
    "2s"  # 16  LengthHi, Length
)
"""Everything before the DMX slots, which start at offset 18."""


@dataclass(frozen=True, kw_only=True)
class ArtDmx:
    """The variable fields of a parsed ArtDmx packet."""

    sequence: int
    physical: int
    portAddress: int  # 15 bits: Net << 8 | Sub-Net << 4 | Universe
    data: bytes

    @property
    def address(self) -> str:
        """The Port-Address as ``net.sub.universe``."""
        return f"{self.portAddress >> 8}.{self.portAddress >> 4 & 0xF}.{self.portAddress & 0xF}"


def opcode(packet: bytes) -> int:
    """The OpCode of an Art-Net packet (after checking its ID)."""
    if packet[:8] != b"Art-Net\0":
        raise ValueError(f"not Art-Net: {packet[:8]!r}")
    return packet[8] | packet[9] << 8  # low byte first


def parse_dmx(packet: bytes) -> ArtDmx:
    """Parse an ArtDmx packet.

    Raises :class:`ValueError` naming the first field that breaks the
    specification: a wrong fixed value, a Net with its top bit set, or a
    length that is odd, out of 2–512, or not the size of the data.
    """
    if len(packet) < DMX_HEADER.size:
        raise ValueError(f"packet of {len(packet)} bytes is too short")
    identifier, opcode, version, sequence, physical, sub_uni, net, length = DMX_HEADER.unpack_from(
        packet
    )
    size = int.from_bytes(length, "big")
    data = bytes(packet[DMX_HEADER.size :])
    expected: dict[str, tuple[object, object]] = {
        "ID": (identifier, b"Art-Net\0"),
        "OpCode": (opcode, 0x5000),  # OpDmx
        "protocol version": (int.from_bytes(version, "big"), 14),
        "Net top bit": (net & 0x80, 0),
        "length is even": (size % 2, 0),
        "length range": (2 <= size <= 512, True),
        "length matches the data": (size, len(data)),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError(f"{field}: {actual!r}, expected {wanted!r}")
    return ArtDmx(sequence=sequence, physical=physical, portAddress=net << 8 | sub_uni, data=data)


class ArtNetReceiver:
    """Collects ArtDmx packets sent to a UDP port; parses each one on arrival
    and remembers which address it came from."""

    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock
        self.sources: list[tuple[str, int]] = []
        """The source address of each packet received, in order."""

    @classmethod
    def localhost(cls) -> Self:
        """A receiver on ``127.0.0.1`` and an ephemeral port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        return cls(sock)

    @property
    def port(self) -> int:
        port: int = self._socket.getsockname()[1]
        return port

    def receive(self, timeout: float = 2.0) -> ArtDmx:
        """The next packet; :class:`TimeoutError` if none arrives in ``timeout`` seconds."""
        self._socket.settimeout(timeout)
        packet, source = self._socket.recvfrom(2048)
        self.sources.append(source)
        return parse_dmx(packet)

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

    def drain(self, quiet: float = 0.2) -> list[ArtDmx]:
        """Every packet that arrives until none has arrived for ``quiet`` seconds."""
        packets: list[ArtDmx] = []
        while True:
            try:
                packets.append(self.receive(quiet))
            except TimeoutError:
                return packets

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


# ------------------------------------------------------------------ discovery


def parse_poll(packet: bytes) -> tuple[int, int]:
    """Check an ArtPoll; return its Flags and DiagPriority."""
    expected: dict[str, tuple[object, object]] = {
        "length": (len(packet) >= 14, True),
        "OpCode": (opcode(packet), 0x2000),  # OpPoll
        "protocol version": (packet[10] << 8 | packet[11], 14),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError(f"{field}: {actual!r}, expected {wanted!r}")
    return packet[12], packet[13]


def poll() -> bytes:
    """An ArtPoll from another controller: ID, OpPoll, version 14, flags 0,
    DiagPriority 0."""
    return b"Art-Net\0" + b"\x00\x20" + b"\x00\x0e" + b"\x00\x00"


def poll_reply(
    *,
    ip: str,
    name: str = "Fake Node",
    net: int = 0,
    sub: int = 0,
    outputs: tuple[int, ...] = (),
    inputs: tuple[int, ...] = (),
    bind_index: int = 0,
    size: int = 239,
    num_ports: int | None = None,
) -> bytes:
    """A node's ArtPollReply, field by field. ``outputs`` are the Universe
    nibbles of its output ports, ``inputs`` of its input-only ports (at most
    four ports in all). ``num_ports`` overrides the port count it states.
    ``size`` may cut it short: 207 bytes is the shortest a consumer must
    accept."""
    ports = [(0x80, u) for u in outputs] + [(0x40, u) for u in inputs]  # 0x40: input
    assert len(ports) <= 4
    if num_ports is None:
        num_ports = len(ports)
    types = bytes(t for t, _ in ports).ljust(4, b"\0")
    sw_out = bytes(u if t == 0x80 else 0 for t, u in ports).ljust(4, b"\0")
    sw_in = bytes(u if t == 0x40 else 0 for t, u in ports).ljust(4, b"\0")
    packet = (
        b"Art-Net\0"  # 0 ID
        + b"\x00\x21"  # 8 OpCode 0x2100, low byte first
        + socket.inet_aton(ip)  # 10 IP
        + b"\x36\x19"  # 14 port 0x1936, low byte first
        + b"\x01\x02"  # 16 firmware version
        + bytes([net, sub])  # 18 NetSwitch, SubSwitch
        + b"\x12\x34"  # 20 OEM, high byte first
        + b"\x00"  # 22 UBEA version
        + b"\xd0"  # 23 Status1
        + b"\x34\x12"  # 24 ESTA code, low byte first
        + name.encode()[:17].ljust(18, b"\0")  # 26 short name
        + name.encode()[:63].ljust(64, b"\0")  # 44 long name
        + b"#0001 [0001] ok".ljust(64, b"\0")  # 108 node report
        + num_ports.to_bytes(2, "big")  # 172 NumPorts
        + types  # 174 PortTypes
        + bytes(4)  # 178 GoodInput
        + bytes(4)  # 182 GoodOutputA
        + sw_in  # 186 SwIn
        + sw_out  # 190 SwOut
        + bytes(3)  # 194 AcnPriority, SwMacro, SwRemote
        + bytes(3)  # 197 spare
        + b"\x00"  # 200 style: StNode
        + bytes(6)  # 201 MAC
        + socket.inet_aton(ip)  # 207 BindIp
        + bytes([bind_index])  # 211 BindIndex
        + b"\x08"  # 212 Status2: 15-bit Port-Addresses
    )
    return packet.ljust(239, b"\0")[:size]


@dataclass(frozen=True, kw_only=True)
class PollReply:
    """The fields of an ArtPollReply that a controller fills in."""

    ip: str
    port: int
    oem: int
    esta: int
    shortName: bytes  # the whole 18-byte field
    longName: bytes  # the whole 64-byte field
    report: bytes  # the whole 64-byte field
    numPorts: int
    ports: bytes  # PortTypes … SwOut: 20 bytes
    style: int
    bindIp: str
    bindIndex: int
    status2: int
    rest: bytes  # everything else after Status2


def parse_poll_reply(packet: bytes) -> PollReply:
    """Check an ArtPollReply's fixed fields and size; return its fields."""
    expected: dict[str, tuple[object, object]] = {
        "size": (len(packet), 239),
        "OpCode": (opcode(packet), 0x2100),  # OpPollReply
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError(f"{field}: {actual!r}, expected {wanted!r}")
    return PollReply(
        ip=socket.inet_ntoa(packet[10:14]),
        port=packet[14] | packet[15] << 8,
        oem=packet[20] << 8 | packet[21],
        esta=packet[24] | packet[25] << 8,
        shortName=packet[26:44],
        longName=packet[44:108],
        report=packet[108:172],
        numPorts=packet[172] << 8 | packet[173],
        ports=packet[174:194],
        style=packet[200],
        bindIp=socket.inet_ntoa(packet[207:211]),
        bindIndex=packet[211],
        status2=packet[212],
        rest=packet[16:20] + packet[22:24] + packet[194:200] + packet[201:207] + packet[213:],
    )


class FakeNode:
    """A UDP socket standing in for an Art-Net node: it answers every ArtPoll
    with its replies (to the poll's source address), and records the ArtDmx
    and ArtPollReplies it receives."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((host, port))
        self.replies: list[bytes] = []
        """What it sends for each ArtPoll (none: it stays silent)."""
        self.polls: list[tuple[str, int]] = []
        """The source of each ArtPoll received."""
        self.dmx: list[ArtDmx] = []
        self.answers: list[bytes] = []
        """ArtPollReplies received (a controller answering its polls)."""

    @property
    def port(self) -> int:
        port: int = self._socket.getsockname()[1]
        return port

    def send(self, packet: bytes, address: tuple[str, int]) -> None:
        self._socket.sendto(packet, address)

    def pump(self, quiet: float = 0.05) -> None:
        """Handle every datagram that arrives until none has for ``quiet`` seconds."""
        self._socket.settimeout(quiet)
        while True:
            try:
                packet, source = self._socket.recvfrom(2048)
            except TimeoutError:
                return
            code = opcode(packet)
            if code == 0x2000:
                parse_poll(packet)
                self.polls.append(source)
                for reply in self.replies:
                    self._socket.sendto(reply, source)
            elif code == 0x5000:
                self.dmx.append(parse_dmx(packet))
            elif code == 0x2100:
                self.answers.append(packet)
            else:
                raise ValueError(f"unexpected OpCode {code:#06x}")

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
