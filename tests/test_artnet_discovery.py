"""Art-Net discovery (phase-6-plan §5.14, step 17): ArtPoll, the node table,
broadcast routes unicasting to discovered nodes, and this console's
ArtPollReply.

The ``lan`` fixture builds a network on the loopback interface:

* a :class:`FakeNode` on ``127.0.0.1``, which stands in for the broadcast
  address of the routes' interface: it receives the polls and the broadcast
  ArtDmx, and answers polls with whatever replies a test gives it;
* an :class:`ArtNetReceiver` on ``127.0.0.2``, the address the announced
  nodes claim: what arrives there was sent unicast to a discovered node.

``ARTNET_PORT`` is patched to the fake node's port, and the interface
lookups to ``127.0.0.1`` and ``127.0.0.0/8``. The console's network is bound
to an ephemeral port, so the fake node answers there.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import Any

import pytest

from artnet_node import (
    ArtNetReceiver,
    FakeNode,
    parse_poll,
    parse_poll_reply,
    poll,
    poll_reply,
)
from busk.compiler.compile import CompiledUniverse
from busk.engine.clock import FakeClock
from busk.engine.loop import Frame
from busk.model.common import UniverseId
from busk.model.output import ArtNetRoute, OutputSettings
from busk.output import artnet
from busk.output.artnet import (
    DRAIN_LIMIT,
    NODE_TIMEOUT,
    POLL_INTERVAL,
    ArtNetNetwork,
    ArtNetSender,
    art_poll,
    art_poll_reply,
)
from busk.output.driver import RouteNotice
from busk.output.scheduler import OutputScheduler, build_routes

DATA = bytes(range(256)) * 2


@dataclass
class Lan:
    node: FakeNode  # at the routes' broadcast address
    unicast: ArtNetReceiver  # at 127.0.0.2, where announced nodes live
    network: ArtNetNetwork


@pytest.fixture
def lan(monkeypatch: pytest.MonkeyPatch) -> Iterator[Lan]:
    with FakeNode("127.0.0.1") as node:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.2", node.port))
        with ArtNetReceiver(sock) as unicast:
            monkeypatch.setattr(artnet, "ARTNET_PORT", node.port)
            monkeypatch.setattr(artnet, "broadcast_address", lambda iface: "127.0.0.1")
            monkeypatch.setattr(
                artnet, "interface_network", lambda iface: IPv4Network("127.0.0.0/8")
            )
            yield Lan(node, unicast, ArtNetNetwork(port=0, name="Busk Console"))


def route(
    address: tuple[int, int, int] = (0, 0, 1), destination: dict[str, str] | None = None
) -> ArtNetRoute:
    net, sub, universe = address
    definition: dict[str, Any] = {
        "id": "r1",
        "universeId": "u1",
        "enabled": True,
        "protocol": "artnet",
        "portAddress": {"net": net, "subNet": sub, "universe": universe},
        "destination": destination or {"kind": "broadcast", "iface": "eth9"},
    }
    return definition  # type: ignore[return-value]


def opened(network: ArtNetNetwork, definition: ArtNetRoute | None = None) -> ArtNetSender:
    sender = ArtNetSender(definition or route(), network=network)
    sender.open()
    assert sender.status().ok, sender.status().detail
    return sender


def texts(network: ArtNetNetwork) -> list[str]:
    notices, network.notices = network.notices, []
    assert not any(n.failed for n in notices)
    return [n.text for n in notices]


def announce(lan: Lan, now: float, *replies: bytes) -> None:
    """Poll (the network's service at ``now``), let the node answer with
    ``replies``, then service again so the answers are read."""
    lan.node.replies = list(replies)
    lan.network._last_poll = -float("inf")  # a poll is due now
    lan.network.service(now)
    lan.node.pump()
    lan.network.service(now)


# --------------------------------------------------------------- the node table


def test_a_poll_reply_puts_the_node_in_the_table_and_its_routes_go_unicast(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        sender.send(DATA, True, 0.0)  # nobody known yet: broadcast
        announce(lan, 0.1, poll_reply(ip="127.0.0.2", outputs=(1,)))
        assert [d.sequence for d in lan.node.dmx] == [1]
        assert texts(lan.network) == ["Art-Net: node 127.0.0.2 'Fake Node' outputs 0.0.1"]
        [(key, node)] = lan.network.nodes.items()
        assert key == (IPv4Address("127.0.0.2"), 0)
        assert (node.shortName, node.longName, node.outputs) == ("Fake Node", "Fake Node", (1,))

        sender.send(DATA, True, 0.2)
        assert [(p.address, p.sequence) for p in lan.unicast.drain(0.05)] == [("0.0.1", 2)]
        lan.node.pump()
        assert len(lan.node.dmx) == 1  # no more broadcast
        assert sender.status().packets == 2
    finally:
        sender.close()


def test_a_silent_node_is_forgotten_and_its_routes_broadcast_again(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        announce(lan, 0.0, poll_reply(ip="127.0.0.2", outputs=(1,)))
        texts(lan.network)
        lan.node.replies = []  # it goes quiet
        lan.network.service(NODE_TIMEOUT)  # not yet: exactly the timeout
        assert lan.network.nodes
        lan.network.service(NODE_TIMEOUT + 0.01)
        assert lan.network.nodes == {}
        assert texts(lan.network) == [
            "Art-Net: node 127.0.0.2 'Fake Node' forgotten (no reply for 10 s)"
        ]
        sender.send(DATA, True, 11.0)
        lan.node.pump()
        assert [d.sequence for d in lan.node.dmx] == [1]
        assert lan.unicast.drain(0.05) == []
    finally:
        sender.close()


def test_each_reply_refreshes_the_node(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        reply = poll_reply(ip="127.0.0.2", outputs=(1,))
        announce(lan, 0.0, reply)
        announce(lan, 8.0, reply)
        lan.network.service(15.0)  # 7 s after the last reply
        assert lan.network.nodes
        assert texts(lan.network) == ["Art-Net: node 127.0.0.2 'Fake Node' outputs 0.0.1"]
    finally:
        sender.close()


def test_only_nodes_on_the_interface_network_that_output_the_port_address_count(
    lan: Lan, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artnet, "interface_network", lambda iface: IPv4Network("127.0.0.0/30"))
    sender = opened(lan.network)
    try:
        announce(
            lan,
            0.0,
            poll_reply(ip="127.0.0.2", name="Other universe", outputs=(2,)),
            poll_reply(ip="127.0.0.9", name="Other network", outputs=(1,)),
            poll_reply(ip="127.0.0.3", name="Inputs only", inputs=(1,)),
            poll_reply(ip="127.0.0.1", name="Busk Console"),  # a controller: no ports
        )
        assert texts(lan.network) == [
            "Art-Net: node 127.0.0.2 'Other universe' outputs 0.0.2",
            "Art-Net: node 127.0.0.9 'Other network' outputs 0.0.1",
        ]
        sender.send(DATA, True, 0.1)
        lan.node.pump()
        assert len(lan.node.dmx) == 1  # still broadcast
        assert lan.unicast.drain(0.05) == []
    finally:
        sender.close()


def test_every_node_outputting_the_port_address_gets_its_own_packet(lan: Lan) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.3", lan.node.port))
    sender = opened(lan.network, route((1, 2, 3)))
    with ArtNetReceiver(sock) as second:
        try:
            announce(
                lan,
                0.0,
                poll_reply(ip="127.0.0.3", net=1, sub=2, outputs=(4, 3)),
                poll_reply(ip="127.0.0.2", net=1, sub=2, outputs=(3,)),
            )
            assert texts(lan.network) == [
                "Art-Net: node 127.0.0.3 'Fake Node' outputs 1.2.3, 1.2.4",
                "Art-Net: node 127.0.0.2 'Fake Node' outputs 1.2.3",
            ]
            sender.send(DATA, True, 0.1)
            assert [p.sequence for p in lan.unicast.drain(0.05)] == [1]
            assert [p.sequence for p in second.drain(0.05)] == [1]  # one count, two copies
            assert sender.status().packets == 2
        finally:
            sender.close()


def test_a_node_with_many_ports_answers_once_per_bind_index(lan: Lan) -> None:
    sender = opened(lan.network, route((0, 0, 6)))
    try:
        announce(
            lan,
            0.0,
            poll_reply(ip="127.0.0.2", outputs=(0, 1, 2, 3), bind_index=1),
            poll_reply(ip="127.0.0.2", outputs=(4, 5, 6, 7), bind_index=2),
        )
        assert texts(lan.network) == [
            "Art-Net: node 127.0.0.2 'Fake Node' outputs 0.0.0, 0.0.1, 0.0.2, 0.0.3",
            "Art-Net: node 127.0.0.2 #2 'Fake Node' outputs 0.0.4, 0.0.5, 0.0.6, 0.0.7",
        ]
        assert len(lan.network.nodes) == 2
        sender.send(DATA, True, 0.1)
        assert [p.address for p in lan.unicast.drain(0.05)] == ["0.0.6"]
    finally:
        sender.close()


def test_a_changed_reply_is_reported_again_and_retargets_the_routes(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        announce(lan, 0.0, poll_reply(ip="127.0.0.2", outputs=(1,)))
        sender.send(DATA, True, 0.1)
        assert len(lan.unicast.drain(0.05)) == 1
        announce(lan, 1.0, poll_reply(ip="127.0.0.2", outputs=(2,)))  # re-patched
        assert texts(lan.network)[-1] == "Art-Net: node 127.0.0.2 'Fake Node' outputs 0.0.2"
        sender.send(DATA, True, 1.1)
        assert lan.unicast.drain(0.05) == []
        lan.node.pump()
        assert len(lan.node.dmx) == 1  # back to broadcast
    finally:
        sender.close()


def test_ports_past_the_stated_count_are_ignored(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        announce(lan, 0.0, poll_reply(ip="127.0.0.2", outputs=(2, 1), num_ports=1))
        assert texts(lan.network) == ["Art-Net: node 127.0.0.2 'Fake Node' outputs 0.0.2"]
    finally:
        sender.close()


def test_a_short_reply_from_an_older_node_is_read(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        announce(lan, 0.0, poll_reply(ip="127.0.0.2", outputs=(1,), size=207))
        assert texts(lan.network) == ["Art-Net: node 127.0.0.2 'Fake Node' outputs 0.0.1"]
        announce(lan, 1.0, poll_reply(ip="127.0.0.2", outputs=(1,), size=206))  # too short
        assert texts(lan.network) == []  # ignored, not an error
    finally:
        sender.close()


def test_a_reply_without_its_address_is_taken_from_its_source(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        announce(lan, 0.0, poll_reply(ip="0.0.0.0", outputs=(1,)))
        assert texts(lan.network) == ["Art-Net: node 127.0.0.1 'Fake Node' outputs 0.0.1"]
    finally:
        sender.close()


def test_closing_the_last_route_empties_the_table(lan: Lan) -> None:
    sender = opened(lan.network)
    announce(lan, 0.0, poll_reply(ip="127.0.0.2", outputs=(1,)))
    version = lan.network.version
    sender.close()
    assert lan.network.nodes == {}
    assert lan.network.version > version
    reopened = opened(lan.network)  # a fresh table: broadcast until a node answers again
    try:
        reopened.send(DATA, True, 1.0)
        lan.node.pump()
        assert len(lan.node.dmx) == 1
    finally:
        reopened.close()


# --------------------------------------------------------------------- polls


def test_polls_go_every_poll_interval_to_each_broadcast_address_once(lan: Lan) -> None:
    first = opened(lan.network)
    second = opened(lan.network, route((0, 0, 2)))  # the same interface
    try:
        for now in (0.0, 1.0, 2.4, POLL_INTERVAL, 4.9, 2 * POLL_INTERVAL):
            lan.network.service(now)
        lan.node.pump()
        assert lan.node.polls == [("127.0.0.1", lan.network.local_port)] * 3  # 0, 2.5, 5 s
    finally:
        first.close()
        second.close()


def test_our_art_poll_matches_the_golden_bytes() -> None:
    assert art_poll() == b"Art-Net\x00\x00\x20\x00\x0e\x00\x00"
    assert parse_poll(art_poll()) == (0, 0)


def test_unicast_routes_do_not_poll(lan: Lan) -> None:
    sender = opened(lan.network, route(destination={"kind": "unicast", "host": "127.0.0.2"}))
    try:
        lan.network.service(0.0)
        lan.node.pump()
        assert lan.node.polls == []
    finally:
        sender.close()


def test_polls_stop_with_the_last_broadcast_route(lan: Lan) -> None:
    unicast = opened(lan.network, route(destination={"kind": "unicast", "host": "127.0.0.2"}))
    broadcast = opened(lan.network)
    try:
        lan.network.service(0.0)
        broadcast.close()
        lan.network.service(POLL_INTERVAL)
        lan.node.pump()
        assert len(lan.node.polls) == 1
    finally:
        unicast.close()


# ------------------------------------------------------------ our ArtPollReply


def golden_reply(ip: str, port: int, name: bytes, report: bytes) -> bytes:
    """This console's ArtPollReply, written out field by field."""
    return (
        b"Art-Net\x00"  # ID
        + b"\x00\x21"  # OpCode 0x2100, low byte first
        + socket.inet_aton(ip)  # IP
        + port.to_bytes(2, "little")  # port, low byte first
        + b"\x00\x00"  # firmware version
        + b"\x00\x00"  # NetSwitch, SubSwitch
        + b"\x00\xff"  # OEM 0x00FF OemUnknown, high byte first
        + b"\x00\x00"  # UBEA version, Status1
        + b"\xf0\x7f"  # ESTA 0x7FF0 (prototype range), low byte first
        + name[:17].ljust(18, b"\x00")  # short name
        + name[:63].ljust(64, b"\x00")  # long name
        + report.ljust(64, b"\x00")  # node report
        + bytes(2)  # NumPorts 0
        + bytes(20)  # PortTypes, GoodInput, GoodOutputA, SwIn, SwOut
        + bytes(6)  # AcnPriority, SwMacro, SwRemote, spare ×3
        + b"\x01"  # style StController
        + bytes(6)  # MAC unknown
        + socket.inet_aton(ip)  # BindIp
        + b"\x01"  # BindIndex: the root device
        + b"\x08"  # Status2: 15-bit Port-Addresses
        + bytes(26)  # GoodOutputB … filler
    )


def test_art_poll_reply_matches_the_golden_bytes() -> None:
    reply = art_poll_reply(IPv4Address("2.0.0.1"), "Busk Console", replies=3)
    assert reply == golden_reply("2.0.0.1", 0x1936, b"Busk Console", b"#0001 [0003] Busk Console")
    fields = parse_poll_reply(reply)
    assert (fields.ip, fields.port, fields.style, fields.bindIndex) == ("2.0.0.1", 6454, 1, 1)
    assert fields.rest == bytes(len(fields.rest))


def test_long_and_non_ascii_names_are_cut_and_replaced() -> None:
    name = "Ö" + "x" * 80
    fields = parse_poll_reply(art_poll_reply(IPv4Address("2.0.0.1"), name, replies=12345))
    assert fields.shortName == b"?" + b"x" * 16 + b"\x00"
    assert fields.longName == b"?" + b"x" * 62 + b"\x00"
    assert fields.report == b"#0001 [2345] ?" + b"x" * 49 + b"\x00"


def test_an_art_poll_from_another_controller_is_answered(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        lan.node.send(poll(), ("127.0.0.1", lan.network.local_port))  # the node polls us
        lan.network._last_poll = 0.0  # keep our own poll out of the way
        lan.network.service(0.0)
        lan.node.pump()
        [answer] = lan.node.answers
        assert answer == golden_reply(
            "127.0.0.1", lan.node.port, b"Busk Console", b"#0001 [0001] Busk Console"
        )
        lan.node.send(poll()[:12], ("127.0.0.1", lan.network.local_port))  # the shortest poll
        lan.network.service(0.1)
        lan.node.pump()
        assert parse_poll_reply(lan.node.answers[1]).report.startswith(b"#0001 [0002]")
    finally:
        sender.close()


def test_other_datagrams_are_ignored(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        target = ("127.0.0.1", lan.network.local_port)
        for junk in (b"", b"hello", b"Art-Net\x00\x00\x50", b"Art-Net\x00\x00\x50\x00\x0e" + DATA):
            lan.node.send(junk, target)
        lan.network._last_poll = 0.0
        lan.network.service(0.0)
        lan.node.pump()
        assert (lan.node.answers, lan.network.nodes, texts(lan.network)) == ([], {}, [])
    finally:
        sender.close()


def test_a_flood_is_read_a_bounded_batch_per_cycle(lan: Lan) -> None:
    sender = opened(lan.network)
    try:
        for _ in range(DRAIN_LIMIT + 10):
            lan.node.send(poll(), ("127.0.0.1", lan.network.local_port))
        lan.network._last_poll = 0.0
        lan.network.service(0.0)
        lan.node.pump()
        assert len(lan.node.answers) == DRAIN_LIMIT
        lan.network.service(0.1)
        lan.node.pump()
        assert len(lan.node.answers) == DRAIN_LIMIT + 10
    finally:
        sender.close()


def test_without_broadcast_routes_nodes_are_forgotten_and_polls_neither_sent_nor_answered(
    lan: Lan,
) -> None:
    unicast = opened(lan.network, route(destination={"kind": "unicast", "host": "127.0.0.2"}))
    sender = opened(lan.network)
    try:
        announce(lan, 0.0, poll_reply(ip="127.0.0.2", outputs=(1,)))
        assert len(lan.network.nodes) == 1
        sender.close()  # the last broadcast route: discovery is off
        assert lan.network.nodes == {}
        lan.node.send(poll(), ("127.0.0.1", lan.network.local_port))
        lan.network.service(2 * POLL_INTERVAL)
        lan.node.pump()
        assert (len(lan.node.polls), lan.node.answers) == (1, [])  # only announce's poll
        unicast.send(DATA, True, 0.0)
        assert [p.sequence for p in lan.unicast.drain(0.05)] == [1]
    finally:
        unicast.close()


# -------------------------------------------------------------- a taken port


def test_a_taken_port_turns_discovery_off(lan: Lan) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:  # another Art-Net program
        other.bind(("", 0))
        network = ArtNetNetwork(port=other.getsockname()[1])
        sender = opened(network)
        try:
            [notice] = network.notices
            assert notice.failed
            assert notice.text.endswith(", without discovery")
            lan.node.send(poll(), ("127.0.0.1", network.local_port))
            lan.node.send(
                poll_reply(ip="127.0.0.2", outputs=(1,)), ("127.0.0.1", network.local_port)
            )
            network.service(0.0)
            lan.node.pump()
            assert (lan.node.polls, lan.node.answers, network.nodes) == ([], [], {})
            sender.send(DATA, True, 0.0)  # still sends, by broadcast
            lan.node.pump()
            assert len(lan.node.dmx) == 1
        finally:
            sender.close()


# ------------------------------------------------------------- the scheduler


def test_the_scheduler_services_discovery_and_reports_nodes(lan: Lan) -> None:
    settings: OutputSettings = {
        "engineHz": 100,
        "sacnSourceName": "Front of house",
        "sacnCid": "6f4e2b3a-0d1c-4e5f-8a9b-0c1d2e3f4a5b",
        "holdLastFrameOnEngineStall": True,
        "routes": [route()],
    }
    universes = (CompiledUniverse(id=UniverseId("u1"), number=1, name="Stage"),)
    routes, notices = build_routes(settings, universes, artnet=lan.network)
    assert notices == []

    class Source:  # a running engine: a new frame (the same bytes) on every read
        @property
        def latest(self) -> Frame:
            return Frame(seq=0, time=0.0, universes=(DATA,))

    output = OutputScheduler(Source(), routes, FakeClock(), artnet=lan.network)
    lan.node.replies = [poll_reply(ip="127.0.0.2", outputs=(1,))]
    output.service(0.0)  # polls, then broadcasts the first frame
    lan.node.send(poll(), ("127.0.0.1", lan.network.local_port))
    lan.node.pump()
    output.service(1.0)  # reads the node's reply (and answers its poll); keep-alive unicast
    lan.node.pump()
    assert output.notices.get() == RouteNotice(
        text="Art-Net: node 127.0.0.2 'Fake Node' outputs 0.0.1", failed=False
    )
    assert output.notices.empty()
    assert [d.sequence for d in lan.node.dmx] == [1]
    assert [p.sequence for p in lan.unicast.drain(0.05)] == [2]
    assert parse_poll_reply(lan.node.answers[0]).longName.startswith(b"Front of house\x00")
    output.close()
    assert lan.network.local_port is None
