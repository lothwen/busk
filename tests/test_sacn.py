"""sACN (E1.31): packet layout, multicast groups, sequence numbers, the
sender and universe discovery.

The header golden is written by hand from the E1.31 data packet table
(phase-1.5-plan §3), field by field; it is never produced by running the code.
Packets are read back with the independent parser in ``sacn_receiver.py``.

Socket tests send unicast to a localhost receiver on an ephemeral port (the
``receiver`` fixture), so no packet leaves the machine. The one exception is
opt-in: set ``BUSK_TEST_IFACE`` to an interface name to send real multicast.

Universe discovery (phase-6-plan §5.15, step 17) is checked against goldens
written field by field from E1.31 §6.4, and sent through fake multicast
sockets.
"""

from __future__ import annotations

import errno
import os
import socket
import uuid
from typing import Any, cast

import pytest

from busk.model.output import SacnRoute
from busk.output import sacn
from busk.output.driver import DriverStatus
from busk.output.sacn import (
    DISCOVERY_INTERVAL,
    PACKET_SIZE,
    SacnSender,
    Sequences,
    UniverseDiscovery,
    data_packet,
    discovery_packets,
    multicast_group,
)
from sacn_receiver import DataPacket, Receiver, parse

CID = uuid.UUID("0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f")
CYCLE = 1 / 44

GOLDEN_HEADER = b"".join(
    [
        b"\x00\x10",  # preamble size
        b"\x00\x00",  # post-amble size
        b"ASC-E1.17\x00\x00\x00",  # ACN packet identifier
        b"\x72\x6e",  # root flags & length: 0x7000 | 622
        b"\x00\x00\x00\x04",  # root vector: VECTOR_ROOT_E131_DATA
        bytes.fromhex("0f6c1b9e3d2a4f7b8e5c1a2b3c4d5e6f"),  # CID
        b"\x72\x58",  # framing flags & length: 0x7000 | 600
        b"\x00\x00\x00\x02",  # framing vector: VECTOR_E131_DATA_PACKET
        b"Busk Console" + bytes(52),  # source name, NUL-padded to 64 bytes
        b"\x64",  # priority: 100
        b"\x00\x00",  # synchronization address: none
        b"\x00",  # sequence number
        b"\x00",  # options
        b"\x00\x01",  # universe: 1
        b"\x72\x0b",  # DMP flags & length: 0x7000 | 523
        b"\x02",  # DMP vector: VECTOR_DMP_SET_PROPERTY
        b"\xa1",  # address type & data type
        b"\x00\x00",  # first property address
        b"\x00\x01",  # address increment
        b"\x02\x01",  # property value count: 513 (START code + 512 slots)
        b"\x00",  # START code: null
    ]
)


def image(*values: int) -> bytes:
    """A 512-byte universe whose first channels hold ``values``."""
    return bytes(values) + bytes(512 - len(values))


A = image(255, 128, 1)
B = image(0, 0, 0, 42)

# ------------------------------------------------------------------ packet


def test_golden_header() -> None:
    packet = data_packet(cid=CID.bytes, sourceName="Busk Console", priority=100, universe=1)
    assert len(GOLDEN_HEADER) == 126
    assert len(packet) == PACKET_SIZE == 638
    assert bytes(packet[:126]) == GOLDEN_HEADER
    assert packet[126:] == bytes(512)


NAME_63 = "é" * 31 + "!"  # 63 UTF-8 bytes, most of them in two-byte characters


@pytest.mark.parametrize(
    ("name", "priority", "universe"),
    [(NAME_63, 0, 1), ("Busk Console", 200, 63999), ("", 100, 256)],
)
def test_fields_parse_back(name: str, priority: int, universe: int) -> None:
    packet = data_packet(cid=CID.bytes, sourceName=name, priority=priority, universe=universe)
    assert parse(bytes(packet)) == DataPacket(
        cid=CID,
        sourceName=name,
        priority=priority,
        syncAddress=0,
        sequence=0,
        options=0,
        universe=universe,
        startCode=0,
        data=bytes(512),
    )


def test_a_63_byte_name_still_ends_in_nul() -> None:
    assert len(NAME_63.encode("utf-8")) == 63
    packet = data_packet(cid=CID.bytes, sourceName=NAME_63, priority=100, universe=1)
    assert packet[44:107] == NAME_63.encode("utf-8")
    assert packet[107] == 0  # the last byte of the 64-byte field


@pytest.mark.parametrize(
    ("universe", "group"),
    [(1, "239.255.0.1"), (256, "239.255.1.0"), (63999, "239.255.249.255")],
)
def test_multicast_groups(universe: int, group: str) -> None:
    assert multicast_group(universe) == group


# --------------------------------------------------------------- sequences


def test_a_universe_counts_from_0_and_wraps_after_255() -> None:
    sequences = Sequences()
    assert [sequences.next(1) for _ in range(258)] == [*range(256), 0, 1]


def test_universes_count_independently() -> None:
    sequences = Sequences()
    drawn = [sequences.next(u) for u in (1, 1, 2, 1, 2, 7)]
    assert drawn == [0, 1, 0, 2, 1, 0]


# ------------------------------------------------------------------ sender


def sacn_route(destination: dict[str, Any], *, universe: int = 1, priority: int = 100) -> SacnRoute:
    return cast(
        SacnRoute,
        {
            "id": "r1",
            "universeId": "u1",
            "enabled": True,
            "protocol": "sacn",
            "universe": universe,
            "priority": priority,
            "destination": destination,
        },
    )


LOCALHOST = {"kind": "unicast", "host": "127.0.0.1"}


def sender(
    destination: dict[str, Any] = LOCALHOST,
    *,
    sequences: Sequences | None = None,
    universe: int = 1,
    priority: int = 100,
) -> SacnSender:
    return SacnSender(
        sacn_route(destination, universe=universe, priority=priority),
        cid=CID.bytes,
        sourceName="Busk Console",
        sequences=Sequences() if sequences is None else sequences,
    )


def test_open_and_send_delivers_one_packet(receiver: Receiver) -> None:
    route = sender(universe=7, priority=150)
    route.open()
    assert route.status() == DriverStatus(ok=True, detail="", packets=0, errors=0)
    route.send(A, True, 0.0)
    assert receiver.receive() == DataPacket(
        cid=CID,
        sourceName="Busk Console",
        priority=150,
        syncAddress=0,
        sequence=0,
        options=0,
        universe=7,
        startCode=0,
        data=A,
    )
    assert route.status() == DriverStatus(ok=True, detail="", packets=1, errors=0)
    assert route.protocol == "sacn"
    assert route.description == "universe 7, unicast 127.0.0.1, priority 150"
    route.close()


def test_sends_follow_the_send_policy(receiver: Receiver) -> None:
    route = sender()
    route.open()
    for k in range(45):  # one change, then just over a second of static data
        route.send(A, k == 0, k * CYCLE)
    route.close()
    data_packets = [p for p in receiver.drain() if not p.terminated]
    # The change, three repeats, then the first keep-alive (cycle 43).
    assert [p.sequence for p in data_packets] == [0, 1, 2, 3, 4]
    assert {p.data for p in data_packets} == {A}


def test_close_sends_three_stream_terminated_packets(receiver: Receiver) -> None:
    route = sender()
    route.open()
    route.send(A, True, 0.0)
    route.send(B, True, CYCLE)
    route.close()
    packets = receiver.drain()
    assert [(p.sequence, p.options, p.data) for p in packets] == [
        (0, 0x00, A),
        (1, 0x00, B),
        (2, 0x40, B),  # Stream_Terminated, carrying the last data
        (3, 0x40, B),
        (4, 0x40, B),
    ]
    assert route.status().packets == 5

    route.close()  # idempotent
    route.send(A, True, 1.0)  # a closed route never sends again
    assert receiver.drain() == []
    assert route.status().packets == 5


def test_closing_a_route_that_never_sent_sends_nothing(receiver: Receiver) -> None:
    route = sender()
    route.open()
    route.close()
    assert receiver.drain() == []


def test_routes_on_one_universe_share_its_sequence(receiver: Receiver) -> None:
    shared = Sequences()
    main = sender(sequences=shared, priority=100)
    backup = sender(sequences=shared, priority=50)  # e.g. multicast plus a unicast backup
    other = sender(sequences=shared, universe=2)
    for route in (main, backup, other):
        route.open()
    for k in range(2):
        for route in (main, backup, other):
            route.send(A, k == 0, k * CYCLE)
    packets = receiver.drain()
    assert [(p.universe, p.priority, p.sequence) for p in packets] == [
        (1, 100, 0),
        (1, 50, 1),
        (2, 100, 0),
        (1, 100, 2),
        (1, 50, 3),
        (2, 100, 1),
    ]
    for route in (main, backup, other):
        route.close()


@pytest.mark.parametrize("iface", ["lo", "127.0.0.1"])
def test_multicast_opens_on_an_interface_name_or_address(iface: str) -> None:
    route = sender({"kind": "multicast", "iface": iface})
    route.open()
    assert route.status().ok, route.status()
    assert route.description == f"universe 1, multicast 239.255.0.1 via {iface}, priority 100"
    route.close()  # never sent: nothing goes out


def test_an_unknown_interface_fails_to_open() -> None:
    route = sender({"kind": "multicast", "iface": "no-such-if0"})
    route.open()
    available = ", ".join(name for _, name in socket.if_nameindex())
    assert route.status() == DriverStatus(
        ok=False,
        detail=f"no network interface 'no-such-if0' (available: {available})",
        packets=0,
        errors=0,
    )
    route.send(A, True, 0.0)  # a route that failed to open does nothing
    route.close()
    assert route.status().errors == 0


def test_an_unresolvable_host_fails_to_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def unresolvable(*args: object, **kwargs: object) -> None:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", unresolvable)  # no DNS query in tests
    route = sender({"kind": "unicast", "host": "lights.invalid"})
    route.open()
    assert route.status() == DriverStatus(
        ok=False,
        detail="cannot resolve host 'lights.invalid': Name or service not known",
        packets=0,
        errors=0,
    )


def test_a_failed_send_is_counted_and_never_raises() -> None:
    # Without SO_BROADCAST the kernel refuses a broadcast before anything goes out.
    route = sender({"kind": "unicast", "host": "255.255.255.255"})
    route.open()
    assert route.status().ok
    route.send(A, True, 0.0)
    detail = f"[Errno {errno.EACCES}] {os.strerror(errno.EACCES)}"
    assert route.status() == DriverStatus(ok=False, detail=detail, packets=0, errors=1)

    # A failed send counts as sent for the keep-alive timer: after the three
    # repeats, the dead link is retried once a keep-alive is due, not every cycle.
    for k in range(1, 45):
        route.send(A, False, k * CYCLE)
    assert route.status().errors == 5  # cycles 0, 1, 2, 3 and 43
    route.close()  # nothing was ever sent, so no termination is attempted
    assert route.status().errors == 5


class FlakySocket:
    """Stands in for a UDP socket whose first ``failures`` sends fail."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.sent: list[bytes] = []

    def setblocking(self, flag: bool) -> None:
        pass

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        if self.failures:
            self.failures -= 1
            raise OSError(errno.ENETUNREACH, "Network is unreachable")
        self.sent.append(bytes(data))
        return len(data)

    def close(self) -> None:
        pass


def test_a_successful_send_restores_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = FlakySocket(failures=1)
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: stub)
    route = sender()
    route.open()
    route.send(A, True, 0.0)
    assert route.status() == DriverStatus(
        ok=False, detail=f"[Errno {errno.ENETUNREACH}] Network is unreachable", packets=0, errors=1
    )
    route.send(A, False, CYCLE)  # the first repeat goes through
    assert route.status() == DriverStatus(ok=True, detail="", packets=1, errors=1)
    assert parse(stub.sent[0]).sequence == 1  # the failed send used sequence 0


@pytest.mark.skipif(
    "BUSK_TEST_IFACE" not in os.environ,
    reason="set BUSK_TEST_IFACE to an interface name to send real multicast",
)
def test_multicast_on_a_real_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    # Universe 63999 at priority 0: a live receiver is unlikely to listen to it,
    # and any other source wins over it.
    iface = os.environ["BUSK_TEST_IFACE"]
    with Receiver.multicast(multicast_group(63999), iface) as receiver:
        monkeypatch.setattr(sacn, "SACN_PORT", receiver.port)
        route = sender({"kind": "multicast", "iface": iface}, universe=63999, priority=0)
        route.open()
        assert route.status().ok, route.status()
        route.send(A, True, 0.0)
        packet = receiver.receive()
        route.close()
    assert (packet.universe, packet.priority, packet.sequence, packet.data) == (63999, 0, 0, A)


# --------------------------------------------------------- universe discovery


def golden_discovery(page: int, last: int, universes: range) -> bytes:
    """A universe discovery packet, field by field (E1.31 §6.4)."""
    size = 120 + 2 * len(universes)
    return b"".join(
        [
            b"\x00\x10",  # preamble size
            b"\x00\x00",  # post-amble size
            b"ASC-E1.17\x00\x00\x00",  # ACN packet identifier
            (0x7000 | (size - 16)).to_bytes(2, "big"),  # root flags & length
            b"\x00\x00\x00\x08",  # root vector: VECTOR_ROOT_E131_EXTENDED
            CID.bytes,
            (0x7000 | (size - 38)).to_bytes(2, "big"),  # framing flags & length
            b"\x00\x00\x00\x02",  # framing vector: VECTOR_E131_EXTENDED_DISCOVERY
            b"Busk Console" + bytes(52),  # source name, NUL-padded to 64 bytes
            bytes(4),  # reserved
            (0x7000 | (size - 112)).to_bytes(2, "big"),  # discovery flags & length
            b"\x00\x00\x00\x01",  # VECTOR_UNIVERSE_DISCOVERY_UNIVERSE_LIST
            bytes([page, last]),
            b"".join(u.to_bytes(2, "big") for u in universes),
        ]
    )


def test_discovery_of_one_universe_matches_the_golden() -> None:
    [packet] = discovery_packets(cid=CID.bytes, sourceName="Busk Console", universes=[1])
    assert packet == golden_discovery(0, 0, range(1, 2))
    assert len(packet) == 122
    assert packet[16:18] == b"\x70\x6a"  # 0x7000 | 106, by hand


def test_600_universes_take_two_pages_sorted_and_without_repeats() -> None:
    universes = [*range(600, 0, -1), 5, 7]  # reversed, with repeats
    packets = discovery_packets(cid=CID.bytes, sourceName="Busk Console", universes=universes)
    assert packets == [
        golden_discovery(0, 1, range(1, 513)),
        golden_discovery(1, 1, range(513, 601)),
    ]
    assert [len(p) for p in packets] == [1144, 296]


def test_no_universe_no_packet() -> None:
    assert discovery_packets(cid=CID.bytes, sourceName="x", universes=[]) == []


class MulticastStub:
    """Stands in for the multicast socket of one interface."""

    def __init__(self, iface: str, log: list[tuple[str, bytes, tuple[str, int]]]) -> None:
        self.iface = iface
        self.log = log
        self.closed = False

    def setblocking(self, flag: bool) -> None:
        pass

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.log.append((self.iface, bytes(data), address))
        return len(data)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def multicast(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bytes, tuple[str, int]]]:
    """Every multicast socket is a stub (except on ``no-such…`` interfaces,
    which fail to open); returns the log of what they send (interface,
    packet, destination)."""
    log: list[tuple[str, bytes, tuple[str, int]]] = []

    def open_stub(iface: str) -> MulticastStub:
        if iface.startswith("no-such"):
            raise OSError(f"no network interface {iface!r}")
        return MulticastStub(iface, log)

    monkeypatch.setattr(sacn, "_multicast_socket", open_stub)
    return log


def multicast_sender(iface: str, universe: int) -> SacnSender:
    return sender({"kind": "multicast", "iface": iface}, universe=universe)


def rounds(log: list[tuple[str, bytes, tuple[str, int]]]) -> list[tuple[str, list[int]]]:
    """The discovery packets in the log, as (interface, universes listed)."""
    found = []
    for iface, packet, destination in log:
        assert destination == ("239.255.250.214", sacn.SACN_PORT)
        assert packet[18:22] == b"\x00\x00\x00\x08"
        count = (len(packet) - 120) // 2
        found.append(
            (iface, [int.from_bytes(packet[120 + 2 * k : 122 + 2 * k]) for k in range(count)])
        )
    return found


def test_discovery_goes_every_10_s_out_of_each_multicast_interface(
    multicast: list[tuple[str, bytes, tuple[str, int]]],
) -> None:
    discovery = UniverseDiscovery()
    discovery.update(
        [
            multicast_sender("eth1", 3),
            multicast_sender("eth0", 1),
            sender(universe=2),  # unicast: listed, but sends no discovery of its own
            multicast_sender("eth0", 1),  # a backup on the same universe: listed once
        ]
    )
    assert discovery.interfaces == ("eth0", "eth1")
    for now in (0.0, 5.0, DISCOVERY_INTERVAL - 0.01, DISCOVERY_INTERVAL, 19.0, 20.0):
        discovery.service(now)
    assert rounds(multicast) == [("eth0", [1, 2, 3]), ("eth1", [1, 2, 3])] * 3  # 0, 10 and 20 s
    discovery.close()
    discovery.service(40.0)
    assert len(multicast) == 6


def test_a_changed_list_goes_out_at_once(
    multicast: list[tuple[str, bytes, tuple[str, int]]],
) -> None:
    discovery = UniverseDiscovery()
    eth0 = [multicast_sender("eth0", 1)]
    discovery.update(eth0)
    discovery.service(0.0)
    discovery.update(eth0)  # the same list: no extra round
    discovery.service(1.0)
    discovery.update([*eth0, multicast_sender("eth0", 9)])
    discovery.service(2.0)
    discovery.update([*eth0, multicast_sender("eth1", 9)])  # the same list, a new interface
    discovery.service(3.0)
    assert rounds(multicast) == [
        ("eth0", [1]),
        ("eth0", [1, 9]),
        ("eth0", [1, 9]),
        ("eth1", [1, 9]),
    ]


def test_unused_interfaces_close_and_unicast_shows_send_nothing(
    multicast: list[tuple[str, bytes, tuple[str, int]]],
) -> None:
    discovery = UniverseDiscovery()
    discovery.update([multicast_sender("eth0", 1)])
    [stub] = discovery._sockets.values()
    discovery.update([sender(universe=1)])  # only unicast left
    assert cast(MulticastStub, stub).closed
    assert discovery.interfaces == ()
    discovery.service(0.0)
    assert multicast == []


def test_the_scheduler_lists_only_the_sacn_routes_it_sends(
    multicast: list[tuple[str, bytes, tuple[str, int]]],
) -> None:
    from busk.compiler.compile import CompiledUniverse
    from busk.engine.clock import FakeClock
    from busk.engine.loop import Frame
    from busk.model.common import UniverseId
    from busk.output.artnet import ArtNetNetwork
    from busk.output.scheduler import OutputScheduler, build_routes

    def route(ident: str, universe: int, *, enabled: bool = True, **destination: str) -> Any:
        return {**sacn_route(destination, universe=universe), "id": ident, "enabled": enabled}

    settings: Any = {
        "engineHz": 100,
        "sacnSourceName": "Busk Console",
        "sacnCid": str(CID),
        "holdLastFrameOnEngineStall": True,
        "routes": [
            route("r1", 5, kind="multicast", iface="eth0"),
            route("r2", 6, enabled=False, kind="multicast", iface="eth0"),
            route("r3", 7, kind="unicast", host="127.0.0.1"),
            route("r4", 8, kind="multicast", iface="no-such-if0"),
        ],
    }
    universes = (CompiledUniverse(id=UniverseId("u1"), number=1, name="Stage"),)
    network = ArtNetNetwork(port=0)
    routes, _ = build_routes(settings, universes, artnet=network)

    class Source:
        latest = Frame(seq=0, time=0.0, universes=(A,))

    output = OutputScheduler(Source(), routes, FakeClock(), artnet=network)
    output.service(0.0)
    output.close()
    assert output._discovery.interfaces == ()  # its sockets closed with the routes
    discovery = [sent for sent in multicast if sent[2][0] == "239.255.250.214"]
    assert rounds(discovery) == [("eth0", [5, 7])]  # r2 is disabled, r4 did not open
    assert discovery[0][1] == golden_discovery(0, 0, range(5, 8, 2))
    assert len(multicast) == 2 + 3  # r1's data packet, then 3 Stream_Terminated on close
