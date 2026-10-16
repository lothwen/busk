"""Route reconnect (phase-7-plan decision 17, §5.15, step 11).

The output scheduler tries again, every ``REOPEN_S``, to open a route that
failed to open, and closes and reopens a route whose status has been failing
for ``FAIL_S``. The first half drives the schedule with fake drivers; the
second uses the real sACN, Art-Net and DMX-USB drivers, with the network
lookups patched (an interface that appears, an address that changes) or a
socket whose interface goes away (``ENETUNREACH``).

Every test calls :meth:`OutputScheduler.service` with output times it
chooses, one cycle at a time: no thread, no sleeping.
"""

from __future__ import annotations

import errno
import itertools
import os
import socket
import types
from collections.abc import Iterator
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

import numpy as np
import pytest

from artnet_node import ArtNetReceiver, opcode
from busk.compiler.compile import CompiledUniverse, OutputLayout
from busk.engine.loop import Frame
from busk.model.common import UniverseId
from busk.model.output import OutputSettings
from busk.output import artnet, dmxusb, sacn
from busk.output.artnet import OP_DMX, OP_POLL, RECHECK_S, ArtNetNetwork, ArtNetSender
from busk.output.driver import DriverStatus, RouteNotice
from busk.output.sacn import SacnSender, Sequences
from busk.output.scheduler import (
    FAIL_S,
    HEALTH_S,
    OUTPUT_HZ,
    REOPEN_S,
    OutputScheduler,
    ScheduledRoute,
)
from dmx_widget import PARAMETERS_40, Widget, dmx_message, image
from sacn_receiver import Receiver

STAGE = CompiledUniverse(id=UniverseId("u1"), number=1, name="Stage")
CYCLE = 1 / OUTPUT_HZ
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"


def test_the_schedule_constants_are_the_plans() -> None:
    assert (REOPEN_S, FAIL_S, HEALTH_S, RECHECK_S) == (2.0, 1.0, 0.1, 2.0)


# ------------------------------------------------------------------ helpers


def settings(*routes: dict[str, Any]) -> OutputSettings:
    return cast(
        OutputSettings,
        {
            "engineHz": 100,
            "sacnSourceName": "Busk Console",
            "sacnCid": CID,
            "holdLastFrameOnEngineStall": True,
            "routes": list(routes),
        },
    )


def sacn_route(route_id: str = "r1", **destination: str) -> dict[str, Any]:
    return {
        "id": route_id,
        "universeId": "u1",
        "enabled": True,
        "protocol": "sacn",
        "universe": 1,
        "priority": 100,
        "destination": destination or {"kind": "unicast", "host": "127.0.0.1"},
    }


def dmx_usb_route(port: Path, *, route_id: str = "r1", enabled: bool = True) -> dict[str, Any]:
    return {
        "id": route_id,
        "universeId": "u1",
        "enabled": enabled,
        "protocol": "dmxUsb",
        "device": {"driver": "enttecPro", "port": str(port)},
        "refreshHz": 40,
    }


def layout(*routes: dict[str, Any]) -> OutputLayout:
    """The layout of a one-universe show with these routes (no dark bytes)."""
    return OutputLayout(
        universes=(STAGE,),
        output=settings(*routes),
        engineHz=100.0,
        darkPositions=np.zeros(0, np.intp),
        darkValues=np.zeros(0, np.uint8),
    )


class Source:
    """Stands in for the engine: whatever frame the test puts in ``latest``."""

    def __init__(self, latest: Frame | None = None) -> None:
        self.latest = latest


def frame(seq: int, show: OutputLayout | None = None, *, on: bool = True) -> Frame:
    """A new frame whose first byte is ``seq``, so every frame is a change."""
    return Frame(
        seq=seq, time=seq / 100, universes=(image(seq % 256),), layout=show, outputEnabled=on
    )


def texts(scheduler: OutputScheduler) -> list[str]:
    """The notices reported since the last call."""
    found = []
    while not scheduler.notices.empty():
        found.append(scheduler.notices.get().text)
    return found


def changes(states: list[bool]) -> list[bool]:
    """``states`` with repeats removed: what a status reporter prints."""
    return [state for k, state in enumerate(states) if k == 0 or state != states[k - 1]]


class Fake:
    """A fake sACN driver whose health the test sets; it records opens,
    closes and the ``changed`` flag of each send."""

    def __init__(self) -> None:
        self.ok = True
        self.opened: list[float] = []  # the output time of each open after the first
        self.closes = 0
        self.sent: list[tuple[float, bool]] = []
        self.now = 0.0

    @property
    def protocol(self) -> Literal["sacn"]:
        return "sacn"

    def open(self) -> None:
        self.opened.append(self.now)

    def send(self, data: bytes, changed: bool, now: float) -> None:
        self.now = now
        self.sent.append((now, changed))

    def close(self) -> None:
        self.closes += 1

    def status(self) -> DriverStatus:
        return DriverStatus(ok=self.ok, detail="" if self.ok else "down", packets=0, errors=0)


def fake_scheduler(driver: Any) -> tuple[OutputScheduler, Source]:
    source = Source(frame(1))
    route = ScheduledRoute(id="r1", row=0, driver=driver, description="test")
    return OutputScheduler(source, [route], clock=cast(Any, None)), source


# --------------------------------------------------- the schedule (fake drivers)


def test_a_route_failing_for_fail_s_is_reopened_then_every_reopen_s() -> None:
    driver = Fake()
    scheduler, source = fake_scheduler(driver)
    for k in range(int(8.0 / CYCLE)):
        now = k * CYCLE
        driver.ok = not 0.5 <= now < 6.0
        source.latest = frame(k + 1)
        scheduler.service(now)
    # Health is read every HEALTH_S, so a reopen comes up to one read late.
    late = HEALTH_S + CYCLE
    assert len(driver.opened) == 3  # none once it is healthy again (at 6 s)
    first = driver.opened[0]
    assert 0.5 + FAIL_S <= first <= 0.5 + FAIL_S + 2 * late
    for before, after in itertools.pairwise(driver.opened):
        assert REOPEN_S <= after - before <= REOPEN_S + late
    assert driver.closes == 3


def test_a_reopened_route_is_offered_its_universe_as_changed_at_once() -> None:
    driver = Fake()
    scheduler, source = fake_scheduler(driver)
    source.latest = frame(1)  # the same frame object throughout: nothing changes
    for k in range(int(2.0 / CYCLE)):
        driver.ok = k * CYCLE < 0.2
        scheduler.service(k * CYCLE)
    assert len(driver.opened) == 1
    after = [changed for now, changed in driver.sent if now > driver.opened[0]]
    assert after[0] is True
    assert not any(after[1:])
    assert [changed for _, changed in driver.sent].count(True) == 2  # the first frame, the reopen


def test_a_route_that_recovers_within_fail_s_is_not_reopened() -> None:
    driver = Fake()
    scheduler, source = fake_scheduler(driver)
    for k in range(int(4.0 / CYCLE)):
        now = k * CYCLE
        driver.ok = not (0.5 <= now < 1.3 or 2.0 <= now < 2.8)
        source.latest = frame(k + 1)
        scheduler.service(now)
    assert driver.opened == []
    assert driver.closes == 0


def test_nothing_is_reopened_while_output_is_off() -> None:
    driver = Fake()
    driver.ok = False
    scheduler, source = fake_scheduler(driver)
    for k in range(int(4.0 / CYCLE)):
        source.latest = frame(k + 1, on=False)
        scheduler.service(k * CYCLE)
    assert driver.opened == []
    source.latest = frame(10_000)
    for k in range(int(4.0 / CYCLE), int(6.0 / CYCLE)):
        scheduler.service(k * CYCLE)
    assert len(driver.opened) == 1  # FAIL_S after output came back


class CountingEnttec(dmxusb.EnttecSender):
    """An Enttec sender that counts the scheduler's opens and closes."""

    calls: ClassVar[list[str]] = []

    def open(self) -> None:
        CountingEnttec.calls.append("open")
        super().open()

    def close(self) -> None:
        CountingEnttec.calls.append("close")
        super().close()


def test_dmx_usb_routes_reopen_themselves_and_are_left_alone(tmp_path: Path) -> None:
    CountingEnttec.calls = []
    driver = CountingEnttec(cast(Any, dmx_usb_route(tmp_path / "ttyUSB9")))
    driver.open()  # the port is missing: failed
    assert driver.status().ok is False
    scheduler, _ = fake_scheduler(driver)
    for k in range(int(5.0 / CYCLE)):
        scheduler.service(k * CYCLE)
    assert CountingEnttec.calls == ["open"]


# ------------------------------------------------- routes that failed to open


@pytest.fixture
def interface(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """``busk-test0``: an interface that is missing until the test sets
    ``up``; then it is the loopback (multicast to it goes nowhere, but sends
    succeed). sACN looks interfaces up by name through ``interface_index``."""
    state = {"up": False}
    real = socket.if_nametoindex("lo")

    def index(name: str) -> int:
        if name == "busk-test0" and state["up"]:
            return real
        raise OSError(f"no network interface {name!r} (available: lo)")

    monkeypatch.setattr(sacn, "interface_index", index)
    return state


def test_an_sacn_route_whose_interface_appears_after_3_s_opens_and_sends(
    interface: dict[str, bool],
) -> None:
    show = layout(sacn_route(kind="multicast", iface="busk-test0"))
    source = Source()
    scheduler = OutputScheduler(source, [], clock=cast(Any, None))  # as the root does
    reported: list[tuple[float, str]] = []
    for k in range(int(6.0 / CYCLE)):
        now = k * CYCLE
        interface["up"] = now >= 3.0
        source.latest = frame(k + 1, show)
        scheduler.service(now)
        reported += [(now, text) for text in texts(scheduler)]
    assert [text for _, text in reported] == [
        "sACN r1: cannot open: no network interface 'busk-test0' (available: lo)",
        "sACN r1: U1 Stage → universe 1, multicast 239.255.0.1 via busk-test0, "
        "priority 100 (sending)",
    ]
    opened_at = reported[1][0]
    assert 2 * REOPEN_S <= opened_at < 2 * REOPEN_S + 2 * CYCLE  # tries at 2 s (no), 4 s (yes)
    [route] = scheduler.routes
    assert route.driver.status().ok is True
    assert route.driver.status().packets > 0
    assert scheduler.opened == [route]  # its counts are printed at the end


def test_a_route_still_failing_keeps_its_schedule_across_a_live_edit(
    interface: dict[str, bool], receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = sacn_route(kind="multicast", iface="busk-test0")
    before = layout(failing)
    after = layout(failing, sacn_route("r2"))  # another route is added
    source = Source()
    scheduler = OutputScheduler(source, [], clock=cast(Any, None))
    calls: list[float] = []
    real = sacn.interface_index
    now = 0.0

    def counted(name: str) -> int:
        calls.append(now)
        return real(name)

    monkeypatch.setattr(sacn, "interface_index", counted)
    for k in range(int(5.0 / CYCLE)):
        now = k * CYCLE
        source.latest = frame(k + 1, before if now < 1.0 else after)
        scheduler.service(now)
    assert texts(scheduler) == [
        "sACN r1: cannot open: no network interface 'busk-test0' (available: lo)",
        "sACN r2: U1 Stage → universe 1, unicast 127.0.0.1, priority 100",
    ]
    # Opened at 0, then every REOPEN_S: the edit at 1 s neither retried it nor reported it again.
    assert [round(at / REOPEN_S) for at in calls] == [0, 1, 2]
    assert [route.id for route in scheduler.routes] == ["r2"]


def test_a_disabled_route_is_never_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sacn, "interface_index", lambda name: calls.append(name) or 1)
    show = layout({**sacn_route(kind="multicast", iface="busk-test0"), "enabled": False})
    source = Source()
    scheduler = OutputScheduler(source, [], clock=cast(Any, None))
    for k in range(int(5.0 / CYCLE)):
        source.latest = frame(k + 1, show)
        scheduler.service(k * CYCLE)
    assert texts(scheduler) == ["sACN r1: disabled"]
    assert calls == []


def test_a_route_that_opens_late_takes_its_place_in_show_order(
    interface: dict[str, bool], receiver: Receiver
) -> None:
    show = layout(sacn_route("r1", kind="multicast", iface="busk-test0"), sacn_route("r2"))
    source = Source()
    scheduler = OutputScheduler(source, [], clock=cast(Any, None))
    for k in range(int(0.5 / CYCLE)):  # the first open fails: the interface is not up …
        interface["up"] = k > 0
        source.latest = frame(k + 1, show)
        scheduler.service(k * CYCLE)
    assert [route.id for route in scheduler.routes] == ["r2"]
    for k in range(int(0.5 / CYCLE), int(2.5 / CYCLE)):  # … the retry at 2 s succeeds
        source.latest = frame(k + 1, show)
        scheduler.service(k * CYCLE)
    assert [route.id for route in scheduler.routes] == ["r1", "r2"]


def test_a_dmx_usb_port_missing_at_start_opens_when_its_symlink_appears(
    tmp_path: Path,
) -> None:
    port = tmp_path / "ttyUSB9"
    show = layout(dmx_usb_route(port))
    source = Source()
    scheduler = OutputScheduler(source, [], clock=cast(Any, None))
    widgets: list[Widget] = []
    try:
        for k in range(int(2.5 / CYCLE)):  # opens at 2 s; the keep-alive is due at 3 s
            now = k * CYCLE
            if now >= 1.0 and not widgets:
                widgets.append(Widget(port))  # plugged in
            source.latest = frame(7, show)  # new frames, the same bytes
            scheduler.service(now)
        assert texts(scheduler) == [
            f"DMX-USB r1: cannot open: {port}: No such file or directory",
            f"DMX-USB r1: U1 Stage → Enttec DMX USB Pro on {port} at 40 Hz (sending)",
        ]
        assert widgets[0].read() == PARAMETERS_40 + dmx_message(image(7))
    finally:
        scheduler.close()
        for widget in widgets:
            widget.unplug()


# ------------------------------------------------------------ sends that fail


class Gone(socket.socket):
    """A socket whose interface can go away: once :attr:`gone`, every send
    fails with ``ENETUNREACH``, as on a socket bound to an unplugged network
    adapter. A socket made afterwards works."""

    made: ClassVar[list[Gone]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.gone = False
        Gone.made.append(self)

    def sendto(self, *args: Any) -> int:  # type: ignore[override]
        if self.gone:
            raise OSError(errno.ENETUNREACH, os.strerror(errno.ENETUNREACH))
        return cast(int, super().sendto(*args))


@pytest.fixture
def unplug(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Make the sACN module's sockets :class:`Gone` sockets; the fixture's
    value unplugs every socket made so far."""
    Gone.made = []
    module = types.SimpleNamespace(**{**vars(socket), "socket": Gone})
    monkeypatch.setattr(sacn, "socket", module)

    def unplug_all() -> None:
        for sock in Gone.made:
            sock.gone = True

    yield unplug_all
    Gone.made = []


def test_a_route_whose_sends_raise_enetunreach_reopens_after_1_s_with_sequences_continuing(
    receiver: Receiver, unplug: Any
) -> None:
    show = layout(sacn_route())
    source = Source()
    scheduler = OutputScheduler(source, [], clock=cast(Any, None))
    states: list[tuple[float, bool]] = []
    for k in range(int(4.0 / CYCLE)):
        now = k * CYCLE
        if k == int(0.5 / CYCLE):
            unplug()
            before = receiver.drain(0.05)
        source.latest = frame(k + 1, show)
        scheduler.service(now)
        if k > 0:
            states.append((now, scheduler.routes[0].driver.status().ok))
    after = receiver.drain(0.05)
    sender = scheduler.routes[0].driver
    assert changes([ok for _, ok in states]) == [True, False, True]  # reported once, no flicker
    failed = next(now for now, ok in states if not ok)
    back = next(now for now, ok in states if ok and now > failed)
    assert FAIL_S <= back - failed <= FAIL_S + 2 * HEALTH_S + 3 * CYCLE
    assert not any(packet.terminated for packet in before + after)  # the stream never ended
    errors = sender.status().errors  # each failed send used a sequence number too
    assert errors > 0
    assert after[0].sequence == (before[-1].sequence + errors + 1) % 256  # one counter throughout
    for packets in (before, after):
        assert all((b.sequence - a.sequence) % 256 == 1 for a, b in itertools.pairwise(packets))
    assert len(Gone.made) == 2  # one reopen: a new socket


def test_a_reopened_sacn_sender_keeps_its_failure_until_a_send_succeeds(
    receiver: Receiver, unplug: Any
) -> None:
    sender = SacnSender(
        cast(Any, sacn_route()), cid=bytes(16), sourceName="Busk", sequences=Sequences()
    )
    sender.open()
    assert sender.status().ok is True  # the first open
    sender.send(image(1), True, 0.0)
    unplug()
    sender.send(image(2), True, 0.1)
    failure = sender.status()
    assert failure.ok is False
    assert failure.detail == f"[Errno {errno.ENETUNREACH}] {os.strerror(errno.ENETUNREACH)}"
    sender.close()  # no Stream_Terminated: they would fail too
    sender.open()
    assert sender.status() == failure  # not "ok" before anything went out
    sender.send(image(3), True, 0.2)
    assert sender.status().ok is True
    packets = receiver.drain(0.05)
    assert [(p.data[0], p.terminated) for p in packets] == [(1, False), (3, False)]


def test_an_sacn_route_closed_while_healthy_still_terminates(receiver: Receiver) -> None:
    sender = SacnSender(
        cast(Any, sacn_route()), cid=bytes(16), sourceName="Busk", sequences=Sequences()
    )
    sender.open()
    sender.send(image(1), True, 0.0)
    sender.close()
    assert [p.terminated for p in receiver.drain(0.05)] == [False, True, True, True]


# ------------------------------------------------- Art-Net broadcast addresses


def test_an_art_net_broadcast_address_that_changes_is_followed(
    artnet_receiver: ArtNetReceiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The broadcast address moves from 127.0.0.1 to 127.0.0.2 (a new DHCP
    lease): the route sends there and the network polls there."""
    address = {"now": "127.0.0.1"}
    monkeypatch.setattr(artnet, "broadcast_address", lambda iface: address["now"])
    monkeypatch.setattr(artnet, "interface_network", lambda iface: IPv4Network("127.0.0.0/8"))
    moved = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    moved.bind(("127.0.0.2", artnet_receiver.port))
    moved.settimeout(0.2)
    network = ArtNetNetwork(port=0)
    route = {
        "id": "r2",
        "universeId": "u1",
        "enabled": True,
        "protocol": "artnet",
        "portAddress": {"net": 0, "subNet": 0, "universe": 1},
        "destination": {"kind": "broadcast", "iface": "eth9"},
    }
    sender = ArtNetSender(cast(Any, route), network=network)
    sender.open()
    try:
        network.service(0.0)  # the first ArtPoll goes to the old address
        assert artnet_receiver.discard() == 1
        sender.send(image(1), True, 0.0)  # schedules the next read at RECHECK_S
        address["now"] = "127.0.0.2"
        sender.send(image(2), True, RECHECK_S - 0.1)  # not read again yet
        assert [p.data[0] for p in artnet_receiver.drain(0.05)] == [1, 2]
        sender.send(image(3), True, RECHECK_S)
        network.service(RECHECK_S)  # polls the new address at once
        received = []
        while True:
            try:
                received.append(moved.recv(2048))
            except TimeoutError:
                break
        assert [opcode(packet) for packet in received] == [OP_DMX, OP_POLL]
        assert received[0][18] == 3
        assert network.notices == [
            RouteNotice(
                text="Art-Net r2: port address 0.0.1, broadcast 127.0.0.2 via eth9 "
                "(the interface's address changed)",
                failed=False,
            )
        ]
        assert sender.description == "port address 0.0.1, broadcast 127.0.0.2 via eth9"
        assert sender.status().ok is True
    finally:
        sender.close()
        moved.close()


def test_a_reopened_art_net_broadcast_route_sends_to_its_new_address(
    artnet_receiver: ArtNetReceiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reopen reads the address again, and the destinations follow it even
    though the node table did not change."""
    address = {"now": "127.0.0.2"}
    monkeypatch.setattr(artnet, "broadcast_address", lambda iface: address["now"])
    monkeypatch.setattr(artnet, "interface_network", lambda iface: IPv4Network("127.0.0.0/8"))
    network = ArtNetNetwork(port=0)
    route = {
        "id": "r2",
        "universeId": "u1",
        "enabled": True,
        "protocol": "artnet",
        "portAddress": {"net": 0, "subNet": 0, "universe": 1},
        "destination": {"kind": "broadcast", "iface": "eth9"},
    }
    keep = ArtNetSender(cast(Any, route), network=network)  # keeps the network's socket open
    keep.open()
    sender = ArtNetSender(cast(Any, route), network=network)
    sender.open()
    try:
        sender.send(image(1), True, 0.0)  # to 127.0.0.2: nobody hears it
        sender.close()
        address["now"] = "127.0.0.1"
        sender.open()
        sender.send(image(2), True, 0.1)
        assert [(p.data[0], p.sequence) for p in artnet_receiver.drain(0.05)] == [(2, 2)]
    finally:
        sender.close()
        keep.close()
