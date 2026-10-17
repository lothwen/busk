"""Art-Net output (phase-6-plan §5.14, step 16): ArtDmx packets, sequence
numbers, send-on-change with a one-second keep-alive, unicast and broadcast
destinations, the shared socket, and the interface lookups of ``netif``.

Packets are checked twice: against golden bytes written out field by field,
and through the independent parser of ``artnet_node.py``. Nothing leaves the
machine: routes send to a receiver on localhost (the ``artnet_receiver``
fixture of ``conftest.py`` patches ``ARTNET_PORT``), and broadcast addresses
come from a patched lookup or a mocked ``ioctl``.
"""

from __future__ import annotations

import errno
import fcntl
import os
import socket
import struct
import sys
from ipaddress import IPv4Network
from typing import Any

import pytest

from artnet_node import ArtNetReceiver, parse_dmx
from busk.model.output import ArtNetRoute
from busk.output import artnet, netif
from busk.output.artnet import (
    PACKET_SIZE,
    ArtNetNetwork,
    ArtNetSender,
    art_dmx,
    format_port_address,
    port_address,
)
from busk.output.driver import DriverStatus, RouteNotice

CYCLE = 1 / 44
DATA = bytes(range(256)) * 2


def route(
    route_id: str = "r1",
    *,
    address: tuple[int, int, int] = (0, 0, 1),
    destination: dict[str, str] | None = None,
) -> ArtNetRoute:
    net, sub, universe = address
    return {
        "id": route_id,
        "universeId": "u1",
        "enabled": True,
        "protocol": "artnet",
        "portAddress": {"net": net, "subNet": sub, "universe": universe},
        "destination": destination or {"kind": "unicast", "host": "127.0.0.1"},  # type: ignore[typeddict-item]
    }


def opened(network: ArtNetNetwork, definition: ArtNetRoute | None = None) -> ArtNetSender:
    sender = ArtNetSender(definition or route(), network=network)
    sender.open()
    assert sender.status().ok, sender.status().detail
    return sender


# ------------------------------------------------------------------ packets


def golden(sequence: int, sub_uni: int, net: int, data: bytes) -> bytes:
    """An ArtDmx packet written out field by field (Art-Net 4)."""
    return (
        b"Art-Net\x00"  # ID
        + b"\x00\x50"  # OpCode 0x5000, low byte first
        + b"\x00\x0e"  # protocol version 14, high byte first
        + bytes([sequence, 0, sub_uni, net])  # Sequence, Physical, SubUni, Net
        + b"\x02\x00"  # length 512, high byte first
        + data
    )


@pytest.mark.parametrize(
    ("address", "sub_uni", "net"),
    [
        pytest.param((0, 0, 0), 0x00, 0x00, id="0.0.0"),
        pytest.param((0, 0, 1), 0x01, 0x00, id="0.0.1"),
        pytest.param((1, 2, 3), 0x23, 0x01, id="1.2.3"),
        pytest.param((127, 15, 15), 0xFF, 0x7F, id="127.15.15: the largest"),
    ],
)
def test_art_dmx_matches_the_golden_bytes(
    address: tuple[int, int, int], sub_uni: int, net: int
) -> None:
    value = port_address({"net": address[0], "subNet": address[1], "universe": address[2]})
    packet = art_dmx(7, value, DATA)
    assert len(packet) == PACKET_SIZE == 530
    assert bytes(packet) == golden(7, sub_uni, net, DATA)
    parsed = parse_dmx(packet)
    assert (parsed.sequence, parsed.physical, parsed.portAddress, parsed.data) == (
        7,
        0,
        value,
        DATA,
    )
    assert format_port_address(value) == parsed.address == ".".join(map(str, address))


def test_a_route_sends_its_universe_to_a_localhost_receiver(
    artnet_receiver: ArtNetReceiver,
) -> None:
    network = ArtNetNetwork(port=0)
    sender = opened(network, route(address=(1, 2, 3)))
    try:
        sender.send(DATA, True, 0.0)
        packet = artnet_receiver.receive()
        assert (packet.address, packet.sequence, packet.physical, packet.data) == (
            "1.2.3",
            1,
            0,
            DATA,
        )
        assert artnet_receiver.sources == [("127.0.0.1", network.local_port)]
        status = sender.status()
        assert (status.ok, status.detail, status.packets, status.errors) == (True, "", 1, 0)
        assert sender.description == "port address 1.2.3, unicast 127.0.0.1"
    finally:
        sender.close()


# ---------------------------------------------------------------- sequences


def test_sequences_run_from_1_to_255_and_wrap_to_1() -> None:
    network = ArtNetNetwork(port=0)
    assert [network.sequence(1) for _ in range(257)] == [*range(1, 256), 1, 2]


def test_each_port_address_counts_on_its_own() -> None:
    network = ArtNetNetwork(port=0)
    assert [network.sequence(pa) for pa in (1, 1, 2, 1, 2, 0x7FFF)] == [1, 2, 1, 3, 2, 1]


def test_routes_sending_one_port_address_share_its_sequence(
    artnet_receiver: ArtNetReceiver,
) -> None:
    network = ArtNetNetwork(port=0)
    main = opened(network, route("r1"))
    backup = opened(network, route("r2"))  # e.g. the same node by name and by address
    other = opened(network, route("r3", address=(0, 0, 2)))
    try:
        for sender in (main, backup, other, main, backup):
            sender.send(DATA, True, 0.0)
        packets = artnet_receiver.drain()
        assert [(p.address, p.sequence) for p in packets] == [
            ("0.0.1", 1),
            ("0.0.1", 2),
            ("0.0.2", 1),
            ("0.0.1", 3),
            ("0.0.1", 4),
        ]
        assert len(set(artnet_receiver.sources)) == 1  # one socket for every route
    finally:
        for sender in (main, backup, other):
            sender.close()


# ------------------------------------------------------- send on change, keep-alive


def send_cycles(changes: set[int], cycles: int, receiver: ArtNetReceiver) -> list[int]:
    """The 44 Hz cycles at which a fresh route sends when its universe changes
    at the cycles in ``changes``, checked against what the receiver got."""
    sender = opened(ArtNetNetwork(port=0))
    sent = []
    try:
        for k in range(cycles):
            before = sender.status().packets
            sender.send(DATA, k in changes, k * CYCLE)
            if sender.status().packets > before:
                sent.append(k)
    finally:
        sender.close()
    assert len(receiver.drain()) == len(sent)
    return sent


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        pytest.param(set(), [0, 44, 88, 132], id="never changed: the first cycle, then 1 s"),
        pytest.param({0}, [0, 44, 88, 132], id="one change, then static"),
        pytest.param({0, 10}, [0, 10, 54, 98, 142], id="a change sends at once, no repeats"),
        # 1 s after cycle 4 is a hair past cycle 48 in floating point.
        pytest.param(set(range(5)), [0, 1, 2, 3, 4, 49, 93, 137], id="every change is sent"),
    ],
)
def test_a_change_is_sent_at_once_and_an_unchanged_universe_every_second(
    changes: set[int], expected: list[int], artnet_receiver: ArtNetReceiver
) -> None:
    assert send_cycles(changes, 160, artnet_receiver) == expected


# ------------------------------------------------------------- the network


def test_the_socket_opens_with_the_first_route_and_closes_with_the_last(
    artnet_receiver: ArtNetReceiver,
) -> None:
    network = ArtNetNetwork(port=0)
    assert network.local_port is None
    first = opened(network)
    port = network.local_port
    second = opened(network, route("r2"))
    assert network.local_port == port is not None
    first.close()
    first.close()  # idempotent: does not release twice
    assert network.local_port == port
    second.send(DATA, True, 0.0)
    assert artnet_receiver.receive().sequence == 1
    second.close()
    assert network.local_port is None
    third = opened(network)  # a route reopened by a live edit
    try:
        third.send(DATA, True, 0.0)
        assert artnet_receiver.receive().sequence == 2  # sequences outlive the socket
    finally:
        third.close()
    assert network.local_port is None


def free_port() -> int:
    """A UDP port nothing is bound to, standing in for the Art-Net port."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("", 0))
        port: int = probe.getsockname()[1]
        return port


def test_the_socket_is_bound_to_the_art_net_port_for_broadcast() -> None:
    free = free_port()
    network = ArtNetNetwork(port=free)
    network.acquire(poll="127.0.0.1")  # a broadcast route
    try:
        sock = network.sock
        assert sock.getsockname() == ("0.0.0.0", free)
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST)
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)
        assert not sock.getblocking()
        assert network.notices == []
    finally:
        network.release(poll="127.0.0.1")


def test_unicast_routes_leave_the_art_net_port_free(artnet_receiver: ArtNetReceiver) -> None:
    free = free_port()
    network = ArtNetNetwork(port=free)
    sender = opened(network)
    try:
        assert network.local_port not in (None, free)
        assert network.notices == []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as visualiser:
            visualiser.bind(("", free))  # without SO_REUSEADDR, as TupperDMX-Simul binds
        sender.send(DATA, True, 0.0)
        assert artnet_receiver.receive().sequence == 1
    finally:
        sender.close()


def test_the_socket_is_on_the_art_net_port_only_while_a_broadcast_route_is_open(
    artnet_receiver: ArtNetReceiver,
) -> None:
    free = free_port()
    network = ArtNetNetwork(port=free)
    unicast = opened(network)
    try:
        network.acquire(poll="127.0.0.1")  # a broadcast route opens
        assert network.local_port == free
        unicast.send(DATA, True, 0.0)  # through the new socket
        network.release(poll="127.0.0.1")  # and closes
        port = network.local_port
        assert port not in (None, free)
        unicast.send(DATA, True, 0.1)
        assert [p.sequence for p in artnet_receiver.drain()] == [1, 2]
        assert artnet_receiver.sources == [("127.0.0.1", free), ("127.0.0.1", port)]
        assert unicast.status().errors == 0
    finally:
        unicast.close()
    assert network.local_port is None


def test_a_taken_port_sends_from_another_one_with_a_notice() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:  # another Art-Net program
        other.bind(("", 0))
        taken = other.getsockname()[1]
        network = ArtNetNetwork(port=taken)
        network.acquire(poll="127.0.0.1")  # a broadcast route
        try:
            port = network.local_port
            assert port not in (None, taken)
            assert network.notices == [
                RouteNotice(
                    text=f"Art-Net: cannot listen on UDP port {taken} (Address already in use; "
                    f"another Art-Net program?): sending from port {port}, without discovery",
                    failed=True,
                )
            ]
        finally:
            network.release(poll="127.0.0.1")


# -------------------------------------------------------------- destinations


def test_a_broadcast_route_sends_to_its_interface_broadcast_address(
    artnet_receiver: ArtNetReceiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def broadcast(iface: str) -> str:
        asked.append(iface)
        return "127.0.0.1"  # stands in for e.g. 10.255.255.255

    monkeypatch.setattr(artnet, "broadcast_address", broadcast)
    monkeypatch.setattr(artnet, "interface_network", lambda iface: IPv4Network("127.0.0.0/8"))
    destination = {"kind": "broadcast", "iface": "eth9"}
    sender = opened(ArtNetNetwork(port=0), route(destination=destination))
    try:
        sender.send(DATA, True, 0.0)
        sender.send(DATA, True, 0.1)
        assert [p.sequence for p in artnet_receiver.drain()] == [1, 2]
        assert asked == ["eth9"]  # looked up once, at open
        assert sender.description == "port address 0.0.1, broadcast 127.0.0.1 via eth9"
    finally:
        sender.close()


@pytest.mark.parametrize(
    ("destination", "detail"),
    [
        pytest.param(
            {"kind": "broadcast", "iface": "no-such-if0"},
            "no network interface 'no-such-if0' (available: {available})",
            id="unknown interface",
        ),
        pytest.param(
            {"kind": "broadcast", "iface": "lo"},
            "no broadcast address on 'lo'",
            id="loopback has no broadcast",
        ),
        pytest.param(
            {"kind": "unicast", "host": "lights.invalid"},
            "cannot resolve host 'lights.invalid': Name or service not known",
            id="unresolvable host",
        ),
    ],
)
def test_a_route_that_cannot_find_its_destination_stays_closed(
    destination: dict[str, str], detail: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unresolvable(*args: object, **kwargs: object) -> None:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", unresolvable)  # no DNS query in tests
    network = ArtNetNetwork(port=0)
    sender = ArtNetSender(route(destination=destination), network=network)
    sender.open()
    status = sender.status()
    available = ", ".join(name for _, name in socket.if_nameindex())
    assert not status.ok
    assert status.detail == detail.format(available=available)
    assert network.local_port is None  # the socket was never opened
    sender.send(DATA, True, 0.0)
    sender.close()
    assert sender.status().packets == 0


def test_a_failed_send_is_counted_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(artnet, "ARTNET_PORT", 0)  # Linux refuses to send to port 0
    sender = opened(ArtNetNetwork(port=0))
    sender.send(DATA, True, 0.0)
    detail = f"[Errno {errno.EINVAL}] {os.strerror(errno.EINVAL)}"
    assert sender.status() == DriverStatus(ok=False, detail=detail, packets=0, errors=1)
    # A failed send counts as sent for the keep-alive timer: retried after 1 s.
    for k in range(1, 46):
        sender.send(DATA, False, k * CYCLE)
    assert sender.status().errors == 2  # cycles 0 and 44
    sender.close()


class FlakySocket:
    """Stands in for the network's UDP socket; its first ``failures`` sends fail."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.sent: list[bytes] = []

    def setsockopt(self, *args: object) -> None:
        pass

    def setblocking(self, flag: bool) -> None:
        pass

    def bind(self, address: tuple[str, int]) -> None:
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
    sender = opened(ArtNetNetwork(port=0))
    sender.send(DATA, True, 0.0)
    assert sender.status() == DriverStatus(
        ok=False, detail=f"[Errno {errno.ENETUNREACH}] Network is unreachable", packets=0, errors=1
    )
    sender.send(DATA, True, CYCLE)
    assert sender.status() == DriverStatus(ok=True, detail="", packets=1, errors=1)
    assert parse_dmx(stub.sent[0]).sequence == 2  # the failed send used sequence 1
    sender.close()


def test_a_closed_route_sends_nothing(artnet_receiver: ArtNetReceiver) -> None:
    sender = opened(ArtNetNetwork(port=0))
    sender.close()
    sender.send(DATA, True, 0.0)
    assert artnet_receiver.drain(0.05) == []
    assert sender.status().packets == 0


# ------------------------------------------------------------------- netif


class FakeIoctl:
    """Answers interface ``ioctl``s from a table: (request, name) → address."""

    def __init__(self, table: dict[tuple[int, str], str]) -> None:
        self.table = table
        self.calls: list[tuple[int, bytes]] = []

    def __call__(self, fd: int, request: int, arg: bytes) -> bytes:
        self.calls.append((request, arg))
        name = arg[:16].rstrip(b"\0").decode()
        try:
            address = self.table[request, name]
        except KeyError:
            raise OSError(99, "Cannot assign requested address") from None
        sockaddr = struct.pack("=H2s4s8s", socket.AF_INET, b"", socket.inet_aton(address), b"")
        return arg[:16] + sockaddr


def test_broadcast_address_reads_the_interface_with_an_ioctl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIoctl({(0x8919, "lo"): "10.1.255.255"})
    monkeypatch.setattr(fcntl, "ioctl", fake)
    assert netif.broadcast_address("lo") == "10.1.255.255"
    request, arg = fake.calls[-1]
    assert request == netif.SIOCGIFBRDADDR == 0x8919
    assert len(arg) == 32
    assert arg[:16] == b"lo".ljust(16, b"\0")


def test_broadcast_address_takes_one_of_the_interface_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIoctl({(0x8915, "lo"): "127.0.0.1", (0x8919, "lo"): "127.255.255.255"})
    monkeypatch.setattr(fcntl, "ioctl", fake)
    assert netif.broadcast_address("127.0.0.1") == "127.255.255.255"
    with pytest.raises(OSError, match=r"^no network interface has the address 192\.0\.2\.1$"):
        netif.broadcast_address("192.0.2.1")


def test_broadcast_address_reports_an_interface_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fcntl, "ioctl", FakeIoctl({}))
    with pytest.raises(OSError, match=r"^no broadcast address on 'lo': Cannot assign"):
        netif.broadcast_address("lo")
    monkeypatch.setattr(fcntl, "ioctl", FakeIoctl({(0x8919, "lo"): "0.0.0.0"}))
    with pytest.raises(OSError, match=r"^no broadcast address on 'lo'$"):
        netif.broadcast_address("lo")


def test_interface_network_combines_the_address_and_the_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeIoctl({(0x8915, "lo"): "10.1.2.3", (0x891B, "lo"): "255.255.240.0"})
    monkeypatch.setattr(fcntl, "ioctl", fake)
    assert netif.interface_network("lo") == IPv4Network("10.1.0.0/20")
    assert [request for request, _ in fake.calls] == [netif.SIOCGIFADDR, netif.SIOCGIFNETMASK]
    assert netif.interface_network("10.1.2.3") == IPv4Network("10.1.0.0/20")  # by address
    monkeypatch.setattr(fcntl, "ioctl", FakeIoctl({}))
    with pytest.raises(OSError, match=r"^no IPv4 address on 'lo': Cannot assign"):
        netif.interface_network("lo")
    with pytest.raises(OSError, match=r"^no network interface 'no-such-if0' \(available: "):
        netif.interface_network("no-such-if0")


def test_the_real_loopback_network() -> None:
    assert netif.interface_network("lo") == IPv4Network("127.0.0.0/8")


@pytest.mark.parametrize(
    "call",
    [netif.broadcast_address, netif.interface_network, lambda _: netif.ipv4_addresses()],
)
def test_interface_lookups_need_linux(monkeypatch: pytest.MonkeyPatch, call: Any) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(OSError, match=r"are read with Linux ioctls$"):
        call("lo")


def test_a_route_off_linux_reports_that_it_cannot_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    sender = ArtNetSender(
        route(destination={"kind": "broadcast", "iface": "en0"}), network=ArtNetNetwork(port=0)
    )
    sender.open()
    assert sender.status().detail == "broadcast addresses are read with Linux ioctls"
