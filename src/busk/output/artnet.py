"""Art-Net 4 output: ArtDmx packets over UDP, with ArtPoll discovery (spec
§14.3, phase-6-plan §5.14).

**Packet.** Every packet is an ArtDmx with all 512 slots: 530 bytes. The
fields, in order: the ID ``"Art-Net\\0"``, the OpCode 0x5000 (little-endian),
the protocol version 14 (big-endian), the sequence, the physical port (0),
SubUni and Net (the Port-Address, low byte first), the length 512
(big-endian), and the data. Each route builds its packet once; a send writes
only the sequence and the data, as sACN does.

**Port-Address.** Art-Net addresses a universe with 15 bits: Net (7 bits),
Sub-Net (4) and Universe (4). Messages write it ``net.sub.universe``, the way
the console's ``route add … artnet`` takes it.

**Sequence numbers** run 1–255 and wrap to 1 (0 tells receivers not to
check the order). They are kept per Port-Address by :class:`ArtNetNetwork`
and shared by the routes that send it, so a node that hears two routes
still sees them increase. They start at 1 on every run.

**Transmission.** :class:`~busk.output.sacn.SendPolicy` with Art-Net's
parameters: a changed universe is sent at once, an unchanged one every
:data:`KEEPALIVE_S` (§14.3). The output scheduler offers each route its
universe at 44 Hz, so a route sends at most 44 packets per second (per
destination).

**Destinations.**

* ``unicast``: the host, resolved once at open, never in the send path.
* ``broadcast``: Art-Net 4 asks controllers to unicast, so the route sends
  to every discovered node that outputs its Port-Address, one packet each.
  While there is none, it sends to the directed broadcast address of its
  interface (:func:`~busk.output.netif.broadcast_address`, read at open and
  again every :data:`RECHECK_S`, so a new address from DHCP is followed,
  with a notice). Only nodes on the interface's network count
  (:func:`~busk.output.netif.interface_network`), so two broadcast routes on
  two lighting networks never feed each other's nodes.

**Discovery.** The output thread calls :meth:`ArtNetNetwork.service` once
per cycle. It reads the datagrams waiting on the socket without blocking (at
most :data:`DRAIN_LIMIT` per cycle, so a flood cannot stall output):

* an ArtPollReply naming at least one output port updates the node table;
  replies without outputs (other controllers, this console's own) are
  ignored. A node with more than four ports sends one reply per group of
  four (its *bind index*), and each is a separate entry;
* an ArtPoll from any controller, this console's own included (Art-Net 4
  asks controllers to answer too), gets an ArtPollReply naming this console
  (the show's ``sacnSourceName``, style controller, no ports), sent to the
  poller's address on the Art-Net port.

Every :data:`POLL_INTERVAL` it sends an ArtPoll to the broadcast address of
each interface that broadcast routes use. A node not heard from for
:data:`NODE_TIMEOUT` is forgotten. Nodes that appear, change or are forgotten
are reported as notices, which the scheduler prints::

    Art-Net: node 2.0.0.10 'DMX Node 1' outputs 0.0.1

**The socket.** All Art-Net traffic of an output scheduler goes through one
UDP socket, owned by :class:`ArtNetNetwork`. It opens with the first Art-Net
route and closes with the last. It has ``SO_REUSEADDR`` and ``SO_BROADCAST``.
While a broadcast route is open it is bound to the Art-Net port, where nodes
answer polls. Otherwise it is bound to an ephemeral port: unicast routes
need no discovery, and a receiver on this machine (a visualiser) can then
have the Art-Net port, whichever program starts first. The cost is that
without a broadcast route this console answers no polls. When the first
broadcast route opens or the last one closes, the socket is opened again on
the other port (senders read :attr:`ArtNetNetwork.sock` on every send) and
the node table is emptied. If the Art-Net port is taken (another Art-Net
program), the socket is bound to an ephemeral port instead, with a notice,
and discovery is off: nodes answer polls on the Art-Net port, which this
console cannot hear. It is non-blocking: a full send buffer is a failed send,
never a stall of the output thread.

**Close** sends nothing: Art-Net has no stream end. Nodes hold the last frame
until their own timeout.

**Failures never raise** (spec §18). A route that cannot open, or a send that
fails, shows up in :meth:`ArtNetSender.status`, and the other routes carry on.
A failed poll or reply is counted in :attr:`ArtNetNetwork.errors`.

**Reopening** (Phase 7) works as for sACN: the output scheduler closes and
reopens a route whose sends keep failing, which resolves its destination
again, and sequence numbers continue (:class:`ArtNetNetwork` owns them). A
reopened route keeps its failure until a send succeeds.
"""

from __future__ import annotations

import math
import socket
import struct
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import Final, Literal

from busk.convert.dmx import UNIVERSE_SIZE
from busk.model.output import ArtNetPortAddress, ArtNetRoute
from busk.output.driver import DriverStatus, RouteNotice
from busk.output.netif import broadcast_address, interface_network, resolve
from busk.output.sacn import SendPolicy

ARTNET_PORT: Final = 6454
"""The Art-Net UDP port (0x1936). Read when a route opens and when polls and
replies go out, so tests can point them at an ephemeral localhost port by
patching it."""

KEEPALIVE_S: Final = 1.0
"""Seconds between packets of an unchanged universe (§14.3)."""

POLL_INTERVAL: Final = 2.5
"""Seconds between ArtPolls (Art-Net 4: every 2.5–3 s)."""

NODE_TIMEOUT: Final = 10.0
"""A node not heard from for this long is forgotten (four missed polls)."""

DRAIN_LIMIT: Final = 64
"""Datagrams read per output cycle at most; the rest wait for the next one."""

RECHECK_S: Final = 2.0
"""Seconds between two reads of a broadcast route's interface address (Phase 7)."""

PROTOCOL_VERSION: Final = 14
"""The Art-Net protocol revision the packets carry."""

OP_POLL: Final = 0x2000
OP_POLL_REPLY: Final = 0x2100
OP_DMX: Final = 0x5000

ID: Final = b"Art-Net\x00"
"""Every Art-Net packet starts with these 8 bytes."""

STYLE_CONTROLLER: Final = 0x01
"""ArtPollReply style ``StController``: a lighting console."""

OEM_UNKNOWN: Final = 0x00FF
"""ArtPollReply OEM code ``OemUnknown``: this console has no registered code."""

ESTA_PROTOTYPE: Final = 0x7FF0
"""An ESTA manufacturer code from the range reserved for prototypes."""

# Fields shared by every packet.
_OPCODE: Final = 8  # little-endian
_PROTOCOL: Final = 10  # big-endian (not in ArtPollReply)

# ArtDmx field offsets (Art-Net 4, "ArtDmx packet definition").
SEQUENCE: Final = 12
_PHYSICAL: Final = 13
_SUB_UNI: Final = 14  # the Port-Address's low byte: Sub-Net × 16 + Universe
_NET: Final = 15  # the Port-Address's high 7 bits
_LENGTH: Final = 16  # big-endian
DATA: Final = 18

PACKET_SIZE: Final = DATA + UNIVERSE_SIZE
"""530 bytes: every packet carries all 512 slots."""

POLL_SIZE: Final = 14
"""An ArtPoll up to DiagPriority; nodes accept 12 bytes or more."""

# ArtPollReply field offsets (Art-Net 4, "ArtPollReply packet definition").
_IP: Final = 10
_PORT: Final = 14  # little-endian
_NET_SWITCH: Final = 18
_SUB_SWITCH: Final = 19
_OEM: Final = 20  # big-endian
_ESTA: Final = 24  # little-endian
_SHORT_NAME: Final = 26  # 18 bytes
_LONG_NAME: Final = 44  # 64 bytes
_NODE_REPORT: Final = 108  # 64 bytes
_NUM_PORTS: Final = 172  # big-endian; at most 4
_PORT_TYPES: Final = 174  # 4 bytes; bit 7: the port outputs Art-Net data as DMX
_SW_OUT: Final = 190  # 4 bytes; low nibble: the port's Universe
_STYLE: Final = 200
_BIND_IP: Final = 207
_BIND_INDEX: Final = 211
_STATUS2: Final = 212  # bit 3: 15-bit Port-Addresses

POLL_REPLY_SIZE: Final = 239
_SHORTEST_POLL_REPLY: Final = 207
"""Consumers accept ArtPollReplies of 207 bytes or more; missing fields are 0."""

_CAN_OUTPUT: Final = 0x80
_PORT_ADDRESS_15_BIT: Final = 0x08
_POWER_OK: Final = 0x0001
"""NodeReport status ``RcPowerOk``."""


def port_address(address: ArtNetPortAddress) -> int:
    """The 15-bit Port-Address of a route's ``portAddress``."""
    return address["net"] << 8 | address["subNet"] << 4 | address["universe"]


def format_port_address(value: int) -> str:
    """A Port-Address as messages write it: ``net.sub.universe``."""
    return f"{value >> 8}.{value >> 4 & 0xF}.{value & 0xF}"


def art_dmx(sequence: int, port_address: int, data: bytes) -> bytearray:
    """An ArtDmx packet for one Port-Address, carrying ``data`` (512 bytes)."""
    packet = _header(PACKET_SIZE, OP_DMX)
    packet[SEQUENCE] = sequence
    packet[_PHYSICAL] = 0
    packet[_SUB_UNI] = port_address & 0xFF
    packet[_NET] = port_address >> 8
    struct.pack_into("!H", packet, _LENGTH, UNIVERSE_SIZE)
    packet[DATA:] = data
    return packet


def art_poll() -> bytes:
    """An ArtPoll asking every node to reply (and only when polled: flags 0,
    no diagnostics)."""
    return bytes(_header(POLL_SIZE, OP_POLL))


def art_poll_reply(ip: IPv4Address, name: str, *, replies: int = 0) -> bytes:
    """This console's ArtPollReply: a controller at ``ip`` called ``name``,
    with no ports. ``replies`` is the count the node report carries.

    The names are ASCII: other characters become ``?``, and both are cut to
    leave their terminating NUL.
    """
    packet = bytearray(POLL_REPLY_SIZE)
    packet[: len(ID)] = ID
    struct.pack_into("<H", packet, _OPCODE, OP_POLL_REPLY)
    packet[_IP : _IP + 4] = ip.packed
    struct.pack_into("<H", packet, _PORT, ARTNET_PORT)
    struct.pack_into("!H", packet, _OEM, OEM_UNKNOWN)
    struct.pack_into("<H", packet, _ESTA, ESTA_PROTOTYPE)
    text = name.encode("ascii", "replace")
    packet[_SHORT_NAME : _SHORT_NAME + 17] = text[:17].ljust(17, b"\0")
    packet[_LONG_NAME : _LONG_NAME + 63] = text[:63].ljust(63, b"\0")
    report = f"#{_POWER_OK:04x} [{replies % 10000:04d}] {name}".encode("ascii", "replace")
    packet[_NODE_REPORT : _NODE_REPORT + 63] = report[:63].ljust(63, b"\0")
    packet[_STYLE] = STYLE_CONTROLLER
    packet[_BIND_IP : _BIND_IP + 4] = ip.packed
    packet[_BIND_INDEX] = 1  # the root device
    packet[_STATUS2] = _PORT_ADDRESS_15_BIT
    return bytes(packet)


@dataclass(frozen=True, kw_only=True)
class Node:
    """What an ArtPollReply says about a node (one bind index of it)."""

    ip: IPv4Address
    bindIndex: int  # 0 or 1: the node itself; 2, 3, …: its further groups of ports
    shortName: str
    longName: str
    outputs: tuple[int, ...]  # the Port-Addresses it outputs as DMX, sorted

    @property
    def label(self) -> str:
        """How notices name it: ``node 2.0.0.10 'DMX Node 1'`` (``#2`` after
        the address for a further bind index)."""
        bind = f" #{self.bindIndex}" if self.bindIndex > 1 else ""
        return f"node {self.ip}{bind} '{self.longName or self.shortName}'"


def parse_poll_reply(packet: bytes, source: str) -> Node | None:
    """The node an ArtPollReply describes; ``None`` if ``packet`` is not one.
    ``source`` is the datagram's sender, used when the reply's IP is 0."""
    if (
        len(packet) < _SHORTEST_POLL_REPLY
        or packet[: len(ID)] != ID
        or struct.unpack_from("<H", packet, _OPCODE)[0] != OP_POLL_REPLY
    ):
        return None
    ip = IPv4Address(packet[_IP : _IP + 4])
    if ip.is_unspecified:
        ip = IPv4Address(source)
    base = (packet[_NET_SWITCH] & 0x7F) << 8 | (packet[_SUB_SWITCH] & 0x0F) << 4
    ports = min(4, struct.unpack_from("!H", packet, _NUM_PORTS)[0])
    outputs = {
        base | packet[_SW_OUT + i] & 0x0F
        for i in range(ports)
        if packet[_PORT_TYPES + i] & _CAN_OUTPUT
    }
    return Node(
        ip=ip,
        bindIndex=packet[_BIND_INDEX] if len(packet) > _BIND_INDEX else 0,
        shortName=_text(packet[_SHORT_NAME : _SHORT_NAME + 18]),
        longName=_text(packet[_LONG_NAME : _LONG_NAME + 64]),
        outputs=tuple(sorted(outputs)),
    )


def _header(size: int, opcode: int) -> bytearray:
    """A zeroed packet of ``size`` bytes with the ID, OpCode and protocol version."""
    packet = bytearray(size)
    packet[: len(ID)] = ID
    struct.pack_into("<H", packet, _OPCODE, opcode)
    struct.pack_into("!H", packet, _PROTOCOL, PROTOCOL_VERSION)
    return packet


def _text(field: bytes) -> str:
    """A NUL-terminated ASCII field as text."""
    return field.split(b"\0", 1)[0].decode("ascii", "replace")


def _opcode(packet: bytes) -> int | None:
    """The OpCode of an Art-Net packet; ``None`` for anything else."""
    if len(packet) < 12 or packet[: len(ID)] != ID:
        return None
    opcode: int = struct.unpack_from("<H", packet, _OPCODE)[0]
    return opcode


type NodeKey = tuple[IPv4Address, int]
"""A node table entry: the node's address and bind index."""


class ArtNetNetwork:
    """The Art-Net socket, sequence numbers and node table, shared by every
    Art-Net route of one output scheduler.

    Each :class:`ArtNetSender` that opens calls :meth:`acquire`, and
    :meth:`release` when it closes: the socket opens with the first route and
    closes with the last, so the scheduler never has to close it. Sequence
    numbers outlive the socket, so a route reopened by a live edit carries on
    counting; the node table does not.

    Threads: the main thread before the output thread starts, then only the
    output thread. No lock is needed.
    """

    def __init__(self, *, port: int | None = None, name: str = "busk") -> None:
        """``port`` is the local UDP port to bind while a broadcast route is
        open: :data:`ARTNET_PORT` (read at open) unless a test passes 0 for an
        ephemeral one. ``name`` is what this console's ArtPollReply says (the
        scheduler sets it from the show's ``sacnSourceName``)."""
        self._port = port
        self.name = name
        self._socket: socket.socket | None = None
        self._users = 0
        self._for_polls = False  # the socket was opened for broadcast routes
        self._listening = False  # bound to the Art-Net port: discovery is on
        self._polled: Counter[str] = Counter()  # broadcast address → routes using it
        self._last_poll = -math.inf
        self._next: dict[int, int] = {}  # Port-Address → its next sequence number
        self._seen: dict[NodeKey, float] = {}  # → when its last reply arrived
        self._replies = 0
        self.nodes: Mapping[NodeKey, Node] = {}
        """The node table, replaced (never mutated) when it changes."""
        self.version = 0
        """Counts the node table's changes, so senders recompute their
        destinations only when it moved."""
        self.errors = 0
        """Polls and replies that failed to send."""
        self.notices: list[RouteNotice] = []
        """What the scheduler should report: a taken port, nodes appearing
        and disappearing. It takes and clears the list."""

    @property
    def local_port(self) -> int | None:
        """The UDP port the socket is bound to; ``None`` while no route uses it."""
        return None if self._socket is None else int(self._socket.getsockname()[1])

    @property
    def sock(self) -> socket.socket:
        """The socket, while a route uses it. Broadcast routes opening and
        closing replace it (see the module docs), so senders read it on
        every send."""
        assert self._socket is not None
        return self._socket

    def acquire(self, poll: str | None = None) -> None:
        """Join, opening the socket for the first user. ``poll`` (a broadcast
        route's) is a broadcast address to send ArtPolls to while this user
        remains; the first one moves the socket to the Art-Net port. Raises
        ``OSError`` if no UDP socket can be made at all."""
        self._rebind(poll is not None or bool(self._polled))
        self._users += 1
        if poll is not None:
            self._polled[poll] += 1

    def release(self, poll: str | None = None) -> None:
        """One user is done (with the ``poll`` it acquired with); the last
        one closes the socket and empties the node table, and the last
        poll moves the socket off the Art-Net port."""
        if poll is not None:
            self._polled[poll] -= 1
            if not self._polled[poll]:
                del self._polled[poll]
        self._users -= 1
        if self._users == 0 and self._socket is not None:
            self._socket.close()
            self._socket = None
            self._seen.clear()
            self._update({})
        else:
            self._rebind(bool(self._polled))

    def move_poll(self, old: str, new: str) -> None:
        """A user's broadcast address changed from ``old`` to ``new``: poll
        ``new`` instead, starting with the next :meth:`service`."""
        self._polled[old] -= 1
        if not self._polled[old]:
            del self._polled[old]
        self._polled[new] += 1
        self._last_poll = -math.inf

    def sequence(self, port_address: int) -> int:
        """The Port-Address's next sequence number: 1, 2, …, 255, 1, …"""
        sequence = self._next.get(port_address, 1)
        self._next[port_address] = sequence % 255 + 1
        return sequence

    def targets(self, port_address: int, network: IPv4Network) -> tuple[str, ...]:
        """The addresses of the nodes on ``network`` that output
        ``port_address``, in address order, each once."""
        found = {
            node.ip
            for node in self.nodes.values()
            if port_address in node.outputs and node.ip in network
        }
        return tuple(str(ip) for ip in sorted(found))

    def service(self, now: float) -> None:
        """One output cycle of discovery: read waiting datagrams, forget
        silent nodes, and poll when due (see the module docs)."""
        sock = self._socket
        if sock is None:
            return
        table = dict(self.nodes)
        for _ in range(DRAIN_LIMIT):
            try:
                packet, (host, _) = sock.recvfrom(2048)
            except OSError:  # BlockingIOError: nothing waiting
                break
            if self._listening:
                self._receive(sock, packet, host, now, table)
        for key, seen in list(self._seen.items()):
            if now - seen > NODE_TIMEOUT:
                del self._seen[key]
                node = table.pop(key)
                self._notice(f"{node.label} forgotten (no reply for {NODE_TIMEOUT:g} s)")
        if table != self.nodes:
            self._update(table)
        if self._listening and self._polled and now - self._last_poll >= POLL_INTERVAL:
            self._last_poll = now
            poll = art_poll()
            for address in sorted(self._polled):
                self._send(sock, poll, address)

    def _receive(
        self,
        sock: socket.socket,
        packet: bytes,
        host: str,
        now: float,
        table: dict[NodeKey, Node],
    ) -> None:
        """Handle one datagram: answer an ArtPoll, record an ArtPollReply."""
        opcode = _opcode(packet)
        if opcode == OP_POLL:
            self._replies += 1
            reply = art_poll_reply(_local_address(host), self.name, replies=self._replies)
            self._send(sock, reply, host)
        elif opcode == OP_POLL_REPLY:
            node = parse_poll_reply(packet, host)
            if node is None or not node.outputs:
                return
            key = (node.ip, node.bindIndex)
            self._seen[key] = now
            if table.get(key) != node:
                table[key] = node
                outputs = ", ".join(map(format_port_address, node.outputs))
                self._notice(f"{node.label} outputs {outputs}")

    def _send(self, sock: socket.socket, packet: bytes, host: str) -> None:
        try:
            sock.sendto(packet, (host, ARTNET_PORT))
        except OSError:
            self.errors += 1

    def _update(self, table: Mapping[NodeKey, Node]) -> None:
        self.nodes = table
        self.version += 1

    def _notice(self, text: str) -> None:
        self.notices.append(RouteNotice(text=f"Art-Net: {text}", failed=False))

    def _rebind(self, polls: bool) -> None:
        """Open the socket, on the Art-Net port if broadcast routes ``polls``;
        open it again if that changed (see the module docs). Raises
        ``OSError`` if no socket can be made, keeping the old one."""
        if self._socket is not None and polls == self._for_polls:
            return
        sock = self._open(polls)
        if self._socket is not None:
            self._socket.close()
            self._seen.clear()
            self._update({})
        self._socket = sock
        self._for_polls = polls

    def _open(self, listen: bool) -> socket.socket:
        """A new socket, bound to the Art-Net port if ``listen`` (to an
        ephemeral one, with a notice, if that is taken), else to an ephemeral
        port."""
        port = ARTNET_PORT if self._port is None else self._port
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setblocking(False)
            if not listen:
                sock.bind(("", 0))
                self._listening = False
                return sock
            try:
                sock.bind(("", port))
            except OSError as exc:
                sock.bind(("", 0))
                self._listening = False
                self.notices.append(
                    RouteNotice(
                        text=f"Art-Net: cannot listen on UDP port {port} ({exc.strerror}; "
                        f"another Art-Net program?): sending from port {sock.getsockname()[1]}, "
                        "without discovery",
                        failed=True,
                    )
                )
            else:
                self._listening = True
        except OSError:
            sock.close()
            raise
        return sock


def _local_address(host: str) -> IPv4Address:
    """This machine's address towards ``host``: the one the kernel would send
    from (connecting a UDP socket sends nothing). 0.0.0.0 if there is no route."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((host, ARTNET_PORT))
            return IPv4Address(probe.getsockname()[0])
    except OSError:
        return IPv4Address(0)


_OK: Final = (True, "")
_NOT_OPEN: Final = (False, "not open")


class ArtNetSender:
    """Sends one show universe to one Art-Net destination; an
    :class:`~busk.output.driver.OutputDriver`.

    Threads: :meth:`open` runs on the main thread before the output thread
    starts; :meth:`send` and :meth:`close` run on the output thread;
    :meth:`status` may be called from any thread. As in
    :class:`~busk.output.sacn.SacnSender`, the immutable ``(ok, detail)``
    pair is replaced only when it changes and the counters are plain ints.
    """

    def __init__(self, route: ArtNetRoute, *, network: ArtNetNetwork) -> None:
        """``network`` is shared by every Art-Net route of the run."""
        self._route = route
        self._network = network
        self._port_address = port_address(route["portAddress"])
        self._policy = SendPolicy(repeats=0, keepalive=KEEPALIVE_S)
        self._packet = art_dmx(0, self._port_address, bytes(UNIVERSE_SIZE))
        self._data = memoryview(self._packet)[DATA:]  # also pins the packet's size
        self._joined = False  # in the network: opened, and not closed since
        self._port = ARTNET_PORT
        self._broadcast = ""  # a broadcast route's fallback address
        self._lan: IPv4Network | None = None  # a broadcast route's interface network
        self._recheck_at: float | None = None  # when a broadcast route reads its address again
        self._version = -1  # the node table version _addresses was computed for
        self._addresses: list[tuple[str, int]] = []
        self._state: tuple[bool, str] = _NOT_OPEN
        self._packets = 0
        self._errors = 0

    @property
    def protocol(self) -> Literal["artnet"]:
        return "artnet"

    @property
    def description(self) -> str:
        """Where the route sends, e.g. ``port address 0.0.1, broadcast
        10.255.255.255 via eth0`` (the address is known once open)."""
        destination = self._route["destination"]
        if destination["kind"] == "unicast":
            where = f"unicast {destination['host']}"
        else:
            where = f"broadcast {self._broadcast or '?'} via {destination['iface']}"
        return f"port address {format_port_address(self._port_address)}, {where}"

    def open(self) -> None:
        """Find the destination, then join the network's socket. Call before
        the first :meth:`send`, and again after :meth:`close` to reopen the
        route (Phase 7).

        On failure (an unknown interface, an unresolvable host, no socket)
        the route stays closed, with ``ok = False`` and the reason as detail.
        Success makes the route ``ok`` only on the first open (see the module
        docs).
        """
        destination = self._route["destination"]
        self._port = ARTNET_PORT
        try:
            if destination["kind"] == "unicast":
                self._addresses = [(resolve(destination["host"]), self._port)]
                self._network.acquire()
            else:
                self._broadcast = broadcast_address(destination["iface"])
                self._lan = interface_network(destination["iface"])
                self._network.acquire(poll=self._broadcast)
                self._version = -1  # the destinations follow the new address
                self._recheck_at = None  # the first send schedules the next read
        except OSError as exc:
            self._state = (False, str(exc))
            return
        self._joined = True
        if self._state is _NOT_OPEN:
            self._state = _OK

    def send(self, data: bytes, changed: bool, now: float) -> None:
        """Transmit ``data`` (512 bytes) if the send policy says a packet is
        due: once to each destination. Does nothing on a route that isn't
        open or was closed."""
        if not self._joined or not self._policy.due(changed, now):
            return
        if self._lan is not None:
            if self._recheck_at is None:
                self._recheck_at = now + RECHECK_S
            elif now >= self._recheck_at:
                self._follow(now)
            if self._version != self._network.version:
                self._version = self._network.version
                nodes = self._network.targets(self._port_address, self._lan)
                self._addresses = [(ip, self._port) for ip in nodes or (self._broadcast,)]
        self._packet[SEQUENCE] = self._network.sequence(self._port_address)
        self._data[:] = data
        sock = self._network.sock
        for address in self._addresses:
            try:
                sock.sendto(self._packet, address)
            except OSError as exc:
                self._errors += 1
                state = (False, str(exc))
                if state != self._state:
                    self._state = state
            else:
                self._packets += 1
                if self._state is not _OK:
                    self._state = _OK

    def close(self) -> None:
        """Leave the network (nothing is sent: Art-Net has no stream end).
        Idempotent; a closed route never sends again."""
        if not self._joined:
            return
        self._joined = False
        self._network.release(poll=self._broadcast or None)

    def status(self) -> DriverStatus:
        ok, detail = self._state
        return DriverStatus(ok=ok, detail=detail, packets=self._packets, errors=self._errors)

    def _follow(self, now: float) -> None:
        """Read a broadcast route's interface address again and follow a
        change (see the module docs). A failed read changes nothing: if the
        interface is gone, the sends fail and the scheduler reopens the route."""
        self._recheck_at = now + RECHECK_S
        destination = self._route["destination"]
        assert destination["kind"] == "broadcast"
        try:
            broadcast = broadcast_address(destination["iface"])
            lan = interface_network(destination["iface"])
        except OSError:
            return
        if broadcast == self._broadcast and lan == self._lan:
            return
        self._network.move_poll(self._broadcast, broadcast)
        self._broadcast, self._lan, self._version = broadcast, lan, -1
        text = f"Art-Net {self._route['id']}: {self.description} (the interface's address changed)"
        self._network.notices.append(RouteNotice(text=text, failed=False))
