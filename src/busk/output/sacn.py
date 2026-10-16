"""sACN output: ANSI E1.31 data packets over UDP (spec §14.4).

**Packet.** Every packet is an E1.31 data packet with a null START code and
all 512 slots: 638 bytes (phase-1.5-plan §3). Each route builds its packet
once. A send writes only the sequence number, the options byte and the DMX
data into that preallocated ``bytearray`` and hands it to ``sendto``, so the
send path allocates nothing of its own.

**Sequence numbers** are kept per sACN universe (:class:`Sequences`), as
E1.31 requires of a source (one CID). Routes that send the same universe,
such as multicast plus a unicast backup to one node, share its counter, so a
receiver that hears both still sees increasing numbers. Validation makes sure
such routes also send the same show universe. Counters start at 0 and are
never persisted (§17): a restart is a new stream for receivers.

**Transmission** follows E1.31 §6.6 (:class:`SendPolicy`). The output
scheduler offers each route its universe at 44 Hz, the DMX512 refresh
ceiling, so a route sends at most 44 packets per second. A change is sent at
once and repeated on the next three cycles, because E1.31 asks for three
packets of non-changing data before suppressing. After that a keep-alive is
sent whenever 0.9 s have passed since the last send. That is inside E1.31's
800–1000 ms keep-alive window and far inside the 2.5 s timeout after which
receivers treat the source as lost.

**Termination.** :meth:`SacnSender.close` sends three packets with the
Stream_Terminated option bit, so receivers release the universe at once
instead of waiting for the timeout. After a crash or ``kill -9`` they fall
back to the timeout, which is how E1.31 is meant to fail. A route whose last
send failed skips them: they would fail too.

**Destinations.**

* *Multicast* goes to ``239.255.{hi}.{lo}`` of the universe number, out of
  the interface that ``destination.iface`` names. It can be an interface name
  (Linux: a ``struct ip_mreqn`` with the interface index) or the interface's
  IPv4 address (any platform). The multicast TTL stays at the OS default of 1,
  because lighting networks are one subnet. Multicast loopback stays on, so
  an sACN viewer on the same machine sees the traffic.
* *Unicast* goes to ``destination.host``, resolved once at open, never in the
  send path.

Both use :data:`SACN_PORT`. Sockets are non-blocking: a full send buffer is a
failed send, never a stall of the output thread.

**Universe discovery** (E1.31 §8; phase-6-plan §5.15). Every
:data:`DISCOVERY_INTERVAL` the output scheduler's :class:`UniverseDiscovery`
lists the sACN universes its routes send, unicast ones included, in
universe discovery packets of up to 512 universes each. They go to the
discovery group ``239.255.250.214`` out of every interface that a multicast
route uses, so sACN tools on the lighting network can see the console. A
show whose sACN routes are all unicast sends no discovery.

**Failures never raise** (spec §18). A route that cannot open, or a send that
fails, shows up in :meth:`SacnSender.status`, and the other routes carry on.
A failed discovery send is counted in :attr:`UniverseDiscovery.errors`.

**Reopening** (Phase 7, phase-7-plan decision 17). The output scheduler
closes and reopens a route whose sends keep failing, which resolves the
interface index and the host again (a USB network adapter plugged back in
gets a new index). Sequence numbers continue: :class:`Sequences` owns them.
A reopened route keeps the failure it was reopened for until a send
succeeds, so an outage is reported once, not once per reopen.
"""

from __future__ import annotations

import ipaddress
import math
import socket
import struct
from collections.abc import Sequence
from typing import Final, Literal

from busk.convert.dmx import UNIVERSE_SIZE
from busk.model.output import SacnRoute
from busk.output.driver import DriverStatus
from busk.output.netif import interface_index, resolve

SACN_PORT: Final = 5568
"""The E1.31 UDP port. Read when a route opens, so tests can point routes at
an ephemeral localhost port by patching it."""

REPEATS: Final = 3
"""Packets of unchanged data sent after a change, before suppression."""

KEEPALIVE_S: Final = 0.9
"""Seconds between packets of unchanged data once suppressed (E1.31: 0.8–1 s)."""

TERMINATION_PACKETS: Final = 3
"""Stream_Terminated packets sent by :meth:`SacnSender.close`."""

STREAM_TERMINATED: Final = 0x40
"""Options bit 6: the source stops sending this universe (E1.31 §6.2.6)."""

VECTOR_ROOT_E131_DATA: Final = 0x00000004
VECTOR_E131_DATA_PACKET: Final = 0x00000002
VECTOR_DMP_SET_PROPERTY: Final = 0x02
VECTOR_ROOT_E131_EXTENDED: Final = 0x00000008
VECTOR_E131_EXTENDED_DISCOVERY: Final = 0x00000002
VECTOR_UNIVERSE_DISCOVERY_UNIVERSE_LIST: Final = 0x00000001

DISCOVERY_UNIVERSE: Final = 64214
"""The universe whose multicast group (239.255.250.214) carries discovery."""

DISCOVERY_INTERVAL: Final = 10.0
"""Seconds between universe discovery rounds (E1.31 §8)."""

UNIVERSES_PER_PAGE: Final = 512
"""The most universes one discovery packet lists."""

# Field offsets of the data packet, one per row of the E1.31 table
# (phase-1.5-plan §3). Multi-byte fields are big-endian.
# Root layer
_PREAMBLE_SIZE: Final = 0
_POSTAMBLE_SIZE: Final = 2
_ACN_PACKET_IDENTIFIER: Final = 4
_ROOT_FLAGS_LENGTH: Final = 16
_ROOT_VECTOR: Final = 18
_CID: Final = 22
# Framing layer
_FRAMING_FLAGS_LENGTH: Final = 38
_FRAMING_VECTOR: Final = 40
_SOURCE_NAME: Final = 44
_PRIORITY: Final = 108
_SYNC_ADDRESS: Final = 109
SEQUENCE: Final = 111
OPTIONS: Final = 112
_UNIVERSE: Final = 113
# DMP layer
_DMP_FLAGS_LENGTH: Final = 115
_DMP_VECTOR: Final = 117
_ADDRESS_DATA_TYPE: Final = 118
_FIRST_PROPERTY_ADDRESS: Final = 119
_ADDRESS_INCREMENT: Final = 121
_PROPERTY_VALUE_COUNT: Final = 123
_START_CODE: Final = 125
DATA: Final = 126

PACKET_SIZE: Final = DATA + UNIVERSE_SIZE
"""638 bytes: every packet carries all 512 slots."""

# Universe discovery packet (E1.31 §6.4, §8): the root layer as above; the
# framing layer has no priority, sync, sequence, options or universe, but 4
# reserved bytes after the source name.
_RESERVED: Final = 108
_DISCOVERY_FLAGS_LENGTH: Final = 112
_DISCOVERY_VECTOR: Final = 114
_PAGE: Final = 118
_LAST_PAGE: Final = 119
_UNIVERSES: Final = 120


def _flags_and_length(offset: int, size: int = PACKET_SIZE) -> int:
    """A PDU's flags (``0x7``: vector, header and data present) and its length,
    which runs from its flags field at ``offset`` to the end of the packet
    (``size`` bytes)."""
    return 0x7000 | (size - offset)


def data_packet(*, cid: bytes, sourceName: str, priority: int, universe: int) -> bytearray:
    """A data packet for one universe, with sequence 0, options 0 and every slot 0.

    ``cid`` is the 16 bytes of the show's UUID. ``sourceName`` must encode to
    at most 63 UTF-8 bytes, so the 64-byte field always ends in NUL; validation
    guarantees both.
    """
    packet = bytearray(PACKET_SIZE)
    rows: tuple[tuple[int, str, int | bytes], ...] = (
        # Root layer
        (_PREAMBLE_SIZE, "H", 0x0010),
        (_POSTAMBLE_SIZE, "H", 0x0000),
        (_ACN_PACKET_IDENTIFIER, "12s", b"ASC-E1.17"),  # NUL-padded to 12 bytes
        (_ROOT_FLAGS_LENGTH, "H", _flags_and_length(_ROOT_FLAGS_LENGTH)),
        (_ROOT_VECTOR, "I", VECTOR_ROOT_E131_DATA),
        (_CID, "16s", cid),
        # Framing layer
        (_FRAMING_FLAGS_LENGTH, "H", _flags_and_length(_FRAMING_FLAGS_LENGTH)),
        (_FRAMING_VECTOR, "I", VECTOR_E131_DATA_PACKET),
        (_SOURCE_NAME, "64s", sourceName.encode("utf-8")),  # NUL-padded to 64 bytes
        (_PRIORITY, "B", priority),
        (_SYNC_ADDRESS, "H", 0),  # no universe synchronisation
        (SEQUENCE, "B", 0),  # written per send
        (OPTIONS, "B", 0),  # written per send
        (_UNIVERSE, "H", universe),
        # DMP layer
        (_DMP_FLAGS_LENGTH, "H", _flags_and_length(_DMP_FLAGS_LENGTH)),
        (_DMP_VECTOR, "B", VECTOR_DMP_SET_PROPERTY),
        # Virtual absolute addresses, a range of equal-size items, 2-byte addresses.
        (_ADDRESS_DATA_TYPE, "B", 0xA1),
        (_FIRST_PROPERTY_ADDRESS, "H", 0x0000),
        (_ADDRESS_INCREMENT, "H", 0x0001),
        (_PROPERTY_VALUE_COUNT, "H", 1 + UNIVERSE_SIZE),  # the START code + the slots
        (_START_CODE, "B", 0x00),  # null START code: dimmer-style data
    )
    for offset, fmt, value in rows:
        struct.pack_into("!" + fmt, packet, offset, value)
    return packet


def discovery_packets(*, cid: bytes, sourceName: str, universes: Sequence[int]) -> list[bytes]:
    """The universe discovery packets listing ``universes``: sorted, each
    once, :data:`UNIVERSES_PER_PAGE` per packet (page 0, 1, …, each naming
    the last page). No packet when there is no universe to list."""
    ordered = sorted(set(universes))
    pages = [
        ordered[start : start + UNIVERSES_PER_PAGE]
        for start in range(0, len(ordered), UNIVERSES_PER_PAGE)
    ]
    packets = []
    for page, listed in enumerate(pages):
        size = _UNIVERSES + 2 * len(listed)
        packet = bytearray(size)
        rows: tuple[tuple[int, str, int | bytes], ...] = (
            # Root layer
            (_PREAMBLE_SIZE, "H", 0x0010),
            (_POSTAMBLE_SIZE, "H", 0x0000),
            (_ACN_PACKET_IDENTIFIER, "12s", b"ASC-E1.17"),
            (_ROOT_FLAGS_LENGTH, "H", _flags_and_length(_ROOT_FLAGS_LENGTH, size)),
            (_ROOT_VECTOR, "I", VECTOR_ROOT_E131_EXTENDED),
            (_CID, "16s", cid),
            # Framing layer
            (_FRAMING_FLAGS_LENGTH, "H", _flags_and_length(_FRAMING_FLAGS_LENGTH, size)),
            (_FRAMING_VECTOR, "I", VECTOR_E131_EXTENDED_DISCOVERY),
            (_SOURCE_NAME, "64s", sourceName.encode("utf-8")),
            (_RESERVED, "I", 0),
            # Universe discovery layer
            (_DISCOVERY_FLAGS_LENGTH, "H", _flags_and_length(_DISCOVERY_FLAGS_LENGTH, size)),
            (_DISCOVERY_VECTOR, "I", VECTOR_UNIVERSE_DISCOVERY_UNIVERSE_LIST),
            (_PAGE, "B", page),
            (_LAST_PAGE, "B", len(pages) - 1),
        )
        for offset, fmt, value in rows:
            struct.pack_into("!" + fmt, packet, offset, value)
        struct.pack_into(f"!{len(listed)}H", packet, _UNIVERSES, *listed)
        packets.append(bytes(packet))
    return packets


def multicast_group(universe: int) -> str:
    """The multicast group of an sACN universe: ``239.255.{hi}.{lo}``."""
    return f"239.255.{universe >> 8}.{universe & 0xFF}"


class Sequences:
    """E1.31 sequence numbers: one counter per sACN universe, shared by the
    routes that send it.

    Only the output thread draws numbers, so no lock is needed.
    """

    def __init__(self) -> None:
        self._next: dict[int, int] = {}

    def next(self, universe: int) -> int:
        """The universe's next sequence number: 0, 1, …, 255, 0, …"""
        sequence = self._next.get(universe, 0)
        self._next[universe] = (sequence + 1) & 0xFF
        return sequence


class SendPolicy:
    """When a route transmits (E1.31 §6.6). Pure: no sockets, time is passed in.

    * A change is due at once, and arms ``repeats`` repeats.
    * Each armed repeat is due on one of the following calls.
    * Otherwise a keep-alive is due once ``keepalive`` seconds have passed
      since the last send. Before the first send, one is always due.

    The defaults are sACN's (:data:`REPEATS`, :data:`KEEPALIVE_S`). Art-Net
    routes use ``SendPolicy(repeats=0, keepalive=1.0)``: a change once, an
    unchanged universe every second (§14.3).
    """

    def __init__(self, repeats: int = REPEATS, keepalive: float = KEEPALIVE_S) -> None:
        self._arm = repeats
        self._keepalive = keepalive
        self._repeats = 0  # repeats still to send
        self._last_sent = -math.inf

    def due(self, changed: bool, now: float) -> bool:
        """Whether to send at output time ``now``. Call once per output cycle;
        a ``True`` answer records ``now`` as the last send."""
        if changed:
            self._repeats = self._arm
        elif self._repeats:
            self._repeats -= 1
        elif now - self._last_sent < self._keepalive:
            return False
        self._last_sent = now
        return True


_OK: Final = (True, "")
_NOT_OPEN: Final = (False, "not open")


class SacnSender:
    """Sends one show universe to one sACN destination; an
    :class:`~busk.output.driver.OutputDriver`.

    Threads: :meth:`open` runs on the main thread before the output thread
    starts; :meth:`send` and :meth:`close` run on the output thread;
    :meth:`status` may be called from any thread. The sender replaces its
    immutable ``(ok, detail)`` pair only when it changes and increments plain
    ``int`` counters, so a reader never sees half an update.
    """

    def __init__(
        self, route: SacnRoute, *, cid: bytes, sourceName: str, sequences: Sequences
    ) -> None:
        """``cid`` and ``sourceName`` come from the show's output settings;
        ``sequences`` is shared by every route of the run."""
        self._route = route
        self._universe = route["universe"]
        self._cid = cid
        self._sourceName = sourceName
        self._sequences = sequences
        self._policy = SendPolicy()
        self._packet = data_packet(
            cid=cid, sourceName=sourceName, priority=route["priority"], universe=self._universe
        )
        self._data = memoryview(self._packet)[DATA:]  # also pins the packet's size
        self._socket: socket.socket | None = None  # None until opened, and once closed
        self._address = ("", 0)
        self._state: tuple[bool, str] = _NOT_OPEN
        self._packets = 0
        self._errors = 0

    @property
    def protocol(self) -> Literal["sacn"]:
        return "sacn"

    @property
    def universe(self) -> int:
        """The sACN universe the route sends."""
        return self._universe

    @property
    def iface(self) -> str | None:
        """The interface a multicast route sends through; ``None`` for unicast."""
        destination = self._route["destination"]
        return destination["iface"] if destination["kind"] == "multicast" else None

    @property
    def cid(self) -> bytes:
        return self._cid

    @property
    def sourceName(self) -> str:
        return self._sourceName

    @property
    def description(self) -> str:
        """Where the route sends, e.g. ``universe 1, multicast 239.255.0.1 via
        eth0, priority 100``."""
        destination = self._route["destination"]
        if destination["kind"] == "multicast":
            where = f"multicast {multicast_group(self._universe)} via {destination['iface']}"
        else:
            where = f"unicast {destination['host']}"
        return f"universe {self._universe}, {where}, priority {self._route['priority']}"

    def open(self) -> None:
        """Create the socket and resolve the destination. Call before the
        first :meth:`send`, and again after :meth:`close` to start a new
        stream (``OUTPUT`` on, or a reopen after failing sends, Phase 7):
        sequence numbers continue, since :class:`Sequences` owns them.

        On failure (an unknown interface, an unresolvable host) the route
        stays closed, with ``ok = False`` and the reason as detail. Success
        makes the route ``ok`` only on the first open: after that a failure
        stays until a send succeeds (see the module docs).
        """
        destination = self._route["destination"]
        try:
            if destination["kind"] == "multicast":
                host = multicast_group(self._universe)
                sock = _multicast_socket(destination["iface"])
            else:
                host = resolve(destination["host"])
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
        except OSError as exc:
            self._state = (False, str(exc))
            return
        self._socket, self._address = sock, (host, SACN_PORT)
        if self._state is _NOT_OPEN:
            self._state = _OK

    def send(self, data: bytes, changed: bool, now: float) -> None:
        """Transmit ``data`` (512 bytes) if :class:`SendPolicy` says a packet
        is due. Does nothing on a route that isn't open or was closed."""
        sock = self._socket
        if sock is None or not self._policy.due(changed, now):
            return
        packet = self._packet
        packet[SEQUENCE] = self._sequences.next(self._universe)
        packet[OPTIONS] = 0
        self._data[:] = data
        self._transmit(sock)

    def close(self) -> None:
        """Send :data:`TERMINATION_PACKETS` Stream_Terminated packets, then
        close the socket. They carry the last data, which receivers ignore,
        and consecutive sequence numbers.

        A route that never sent a packet has nothing to terminate, and one
        whose last send failed skips them (they would fail too). Idempotent;
        a closed route sends nothing until it is opened again.
        """
        sock, self._socket = self._socket, None
        if sock is None:
            return
        try:
            if self._packets and self._state[0]:
                self._packet[OPTIONS] = STREAM_TERMINATED
                for _ in range(TERMINATION_PACKETS):
                    self._packet[SEQUENCE] = self._sequences.next(self._universe)
                    self._transmit(sock)
        finally:
            sock.close()

    def status(self) -> DriverStatus:
        ok, detail = self._state
        return DriverStatus(ok=ok, detail=detail, packets=self._packets, errors=self._errors)

    def _transmit(self, sock: socket.socket) -> None:
        """Send the packet; count the outcome and note a change of state."""
        try:
            sock.sendto(self._packet, self._address)
        except OSError as exc:
            self._errors += 1
            state = (False, str(exc))
            if state != self._state:
                self._state = state
        else:
            self._packets += 1
            if self._state is not _OK:
                self._state = _OK


def _multicast_socket(iface: str) -> socket.socket:
    """A UDP socket whose multicast leaves through ``iface``: the IPv4 address
    of an interface (any platform), or an interface name (Linux)."""
    try:
        option = ipaddress.IPv4Address(iface).packed  # struct in_addr
    except ValueError:
        # struct ip_mreqn {imr_multiaddr, imr_address, imr_ifindex}: only the index is used.
        option = struct.pack("=4s4si", bytes(4), bytes(4), interface_index(iface))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, option)
    except OSError as exc:
        sock.close()
        raise OSError(f"cannot send multicast via {iface!r}: {exc.strerror}") from None
    return sock


class UniverseDiscovery:
    """Sends E1.31 universe discovery for the sACN routes of one output
    scheduler (see the module docs).

    The scheduler calls :meth:`update` with its open sACN senders whenever
    its routes change, and :meth:`service` once per output cycle, both on the
    output thread (``update`` also on the main thread before it starts).
    """

    def __init__(self) -> None:
        self._packets: list[bytes] = []
        self._sockets: dict[str, socket.socket] = {}  # interface → multicast socket
        self._last = -math.inf
        self.errors = 0
        """Discovery packets that failed to send, and interfaces that could
        not be opened."""

    @property
    def interfaces(self) -> tuple[str, ...]:
        """The interfaces discovery goes out of, sorted."""
        return tuple(sorted(self._sockets))

    @property
    def packets(self) -> tuple[bytes, ...]:
        """The packets of each discovery round."""
        return tuple(self._packets)

    def update(self, senders: Sequence[SacnSender]) -> None:
        """List the universes of ``senders``, out of their multicast
        interfaces: open sockets for new interfaces, close unused ones. A
        changed list, or a new interface, gets a round on the next
        :meth:`service`."""
        wanted = {sender.iface for sender in senders if sender.iface is not None}
        before = set(self._sockets)
        for iface in set(self._sockets) - wanted:
            self._sockets.pop(iface).close()
        for iface in sorted(wanted - set(self._sockets)):
            try:
                sock = _multicast_socket(iface)
                sock.setblocking(False)
            except OSError:
                self.errors += 1
                continue
            self._sockets[iface] = sock
        packets = (
            discovery_packets(
                cid=senders[0].cid,
                sourceName=senders[0].sourceName,
                universes=[sender.universe for sender in senders],
            )
            if senders
            else []
        )
        if packets != self._packets or set(self._sockets) - before:
            self._packets = packets
            self._last = -math.inf

    def service(self, now: float) -> None:
        """Send a discovery round if one is due."""
        if not self._packets or now - self._last < DISCOVERY_INTERVAL:
            return
        self._last = now
        group = (multicast_group(DISCOVERY_UNIVERSE), SACN_PORT)
        for sock in self._sockets.values():
            for packet in self._packets:
                try:
                    sock.sendto(packet, group)
                except OSError:
                    self.errors += 1

    def close(self) -> None:
        """Close the sockets; nothing is sent afterwards. Idempotent."""
        for sock in self._sockets.values():
            sock.close()
        self._sockets.clear()
        self._packets = []
