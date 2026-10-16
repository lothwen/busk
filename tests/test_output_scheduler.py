"""The output scheduler (§14) and ``build_routes``.

The scheduler tests drive ``service(now)`` directly with fake drivers that
record their calls; ``run`` is driven by a :class:`FakeClock`. The
``build_routes`` and hold-last-frame tests use real sACN and Art-Net senders
and localhost receivers.
"""

from __future__ import annotations

import io
import socket
import threading
import uuid
from typing import Any, Literal, cast

import pytest

from artnet_node import ArtNetReceiver
from busk.compiler.compile import CompiledUniverse
from busk.engine.clock import FakeClock
from busk.engine.loop import Frame
from busk.model.common import UniverseId
from busk.model.output import OutputSettings
from busk.output.artnet import ArtNetNetwork
from busk.output.console import ConsoleOutput
from busk.output.driver import DriverStatus
from busk.output.scheduler import (
    OUTPUT_HZ,
    OutputScheduler,
    RouteNotice,
    ScheduledRoute,
    build_routes,
)
from sacn_receiver import Receiver

STAGE = CompiledUniverse(id=UniverseId("u1"), number=1, name="Stage")
SIDE = CompiledUniverse(id=UniverseId("u2"), number=2, name="Side")
CYCLE = 1 / OUTPUT_HZ


def image(*values: int) -> bytes:
    """A 512-byte universe whose first channels hold ``values``."""
    return bytes(values) + bytes(512 - len(values))


A, B, C = image(1), image(2), image(3)


def frame(seq: int, *universes: bytes) -> Frame:
    return Frame(seq=seq, time=seq / 100, universes=universes)


class Source:
    """Stands in for the engine: whatever frame the test puts in ``latest``."""

    def __init__(self, latest: Frame | None = None) -> None:
        self.latest = latest


class Recorder:
    """A fake driver that records its calls."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, bool, float]] = []
        self.closed = 0

    @property
    def protocol(self) -> Literal["sacn"]:
        return "sacn"

    def open(self) -> None:
        pass

    def send(self, data: bytes, changed: bool, now: float) -> None:
        self.sent.append((data, changed, now))

    def close(self) -> None:
        self.closed += 1

    def status(self) -> DriverStatus:
        return DriverStatus(ok=True, detail="", packets=len(self.sent), errors=0)

    @property
    def changes(self) -> list[bool]:
        return [changed for _, changed, _ in self.sent]


class Faulty(Recorder):
    """A driver with a bug: ``send`` and ``close`` raise after recording the call."""

    def send(self, data: bytes, changed: bool, now: float) -> None:
        super().send(data, changed, now)
        raise RuntimeError("driver bug")

    def close(self) -> None:
        super().close()
        raise RuntimeError("driver bug")


def route(driver: Recorder, row: int = 0, route_id: str = "r1") -> ScheduledRoute:
    return ScheduledRoute(id=route_id, row=row, driver=driver, description="test")


def scheduler(
    source: Source, *routes: ScheduledRoute, console: ConsoleOutput | None = None
) -> OutputScheduler:
    return OutputScheduler(source, routes, FakeClock(), console)


# ------------------------------------------------------------------ service


def test_nothing_is_sent_before_the_first_frame() -> None:
    recorder = Recorder()
    scheduler(Source(), route(recorder)).service(0.0)
    assert recorder.sent == []


def test_the_first_frame_flags_every_universe_as_changed() -> None:
    stage, side = Recorder(), Recorder()
    scheduler(Source(frame(1, A, B)), route(stage, 0), route(side, 1)).service(0.5)
    assert stage.sent == [(A, True, 0.5)]
    assert side.sent == [(B, True, 0.5)]


def test_the_same_frame_or_equal_bytes_flag_nothing() -> None:
    source, recorder = Source(frame(1, A)), Recorder()
    output = scheduler(source, route(recorder))
    output.service(0.0)
    output.service(CYCLE)  # the same Frame object
    source.latest = frame(2, image(1))  # a new Frame with equal bytes
    output.service(2 * CYCLE)
    assert recorder.changes == [True, False, False]


def test_a_new_frame_flags_exactly_the_universes_that_changed() -> None:
    source, stage, side = Source(frame(1, A, B)), Recorder(), Recorder()
    output = scheduler(source, route(stage, 0), route(side, 1))
    output.service(0.0)
    source.latest = frame(2, A, C)
    output.service(CYCLE)
    source.latest = frame(3, B, C)
    output.service(2 * CYCLE)
    assert stage.changes == [True, False, True]
    assert side.changes == [True, True, False]
    assert [data for data, _, _ in side.sent] == [B, C, C]


def test_each_route_gets_its_own_universes_row() -> None:
    first, second, third = Recorder(), Recorder(), Recorder()
    routes = route(first, 1, "r1"), route(second, 0, "r2"), route(third, 1, "r3")
    scheduler(Source(frame(1, A, B)), *routes).service(0.0)
    assert [r.sent[0][0] for r in (first, second, third)] == [B, A, B]


def test_a_faulty_driver_is_counted_and_isolated() -> None:
    source, stream = Source(frame(1, A)), io.StringIO()
    faulty, healthy = route(Faulty(), route_id="r1"), route(Recorder(), route_id="r2")
    console = ConsoleOutput(source, [STAGE], stream)
    output = scheduler(source, faulty, healthy, console=console)
    output.service(0.0)
    output.service(CYCLE)
    assert (faulty.faults, healthy.faults) == (2, 0)
    assert cast(Recorder, healthy.driver).changes == [True, False]
    assert stream.getvalue() == "[frame 1] U1 Stage: 1=1\n"


def test_a_stalled_engine_keeps_the_last_frame_going_out() -> None:
    source, recorder = Source(frame(7, A)), Recorder()  # the engine never publishes again
    output = scheduler(source, route(recorder))
    for k in range(100):
        output.service(k * CYCLE)
    assert recorder.changes == [True] + [False] * 99
    assert {data for data, _, _ in recorder.sent} == {A}


# ---------------------------------------------------------------------- run


def test_run_services_at_output_hz_and_makes_a_final_pass() -> None:
    clock = FakeClock()
    stop = threading.Event()
    reads: list[float] = []

    class CountingSource:
        @property
        def latest(self) -> Frame | None:
            reads.append(clock.now())
            if len(reads) == 10:
                stop.set()
            return None

    OutputScheduler(CountingSource(), [], clock).run(stop)
    # Ten cycles at 44 Hz, then the final pass once the loop sees ``stop``.
    assert reads == [k / OUTPUT_HZ for k in range(11)]


def test_run_closes_every_driver_exactly_once() -> None:
    stop = threading.Event()
    stop.set()  # stopped before the first cycle: only the final pass runs
    faulty, healthy = route(Faulty(), route_id="r1"), route(Recorder(), route_id="r2")
    scheduler(Source(frame(1, A)), faulty, healthy).run(stop)
    assert cast(Recorder, healthy.driver).sent == [(A, True, 0.0)]
    assert cast(Recorder, faulty.driver).closed == cast(Recorder, healthy.driver).closed == 1
    assert faulty.faults == 2  # its send and its close raised


def test_run_closes_the_drivers_even_when_a_cycle_raises() -> None:
    class BrokenStream(io.StringIO):
        def write(self, text: str) -> int:
            raise BrokenPipeError("stdout went away")

    source, recorder = Source(frame(1, A)), Recorder()
    console = ConsoleOutput(source, [STAGE], BrokenStream())
    with pytest.raises(BrokenPipeError):
        scheduler(source, route(recorder), console=console).run(threading.Event())
    assert recorder.closed == 1


# ------------------------------------------------------------- build_routes

CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"


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


def sacn_route(
    route_id: str,
    *,
    universe_id: str = "u1",
    universe: int = 1,
    priority: int = 100,
    enabled: bool = True,
    destination: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": route_id,
        "universeId": universe_id,
        "enabled": enabled,
        "protocol": "sacn",
        "universe": universe,
        "priority": priority,
        "destination": destination or {"kind": "unicast", "host": "127.0.0.1"},
    }


def artnet_route(
    route_id: str,
    *,
    universe_id: str = "u1",
    address: tuple[int, int, int] = (0, 0, 0),
    destination: dict[str, str] | None = None,
) -> dict[str, Any]:
    net, sub, universe = address
    return {
        "id": route_id,
        "universeId": universe_id,
        "enabled": True,
        "protocol": "artnet",
        "portAddress": {"net": net, "subNet": sub, "universe": universe},
        "destination": destination or {"kind": "unicast", "host": "127.0.0.1"},
    }


def close(routes: list[ScheduledRoute]) -> None:
    for each in routes:
        each.driver.close()


def test_build_routes_opens_enabled_sacn_and_art_net_routes_and_explains_the_rest() -> None:
    network = ArtNetNetwork(port=0)
    dmx_usb = {
        "id": "r4",
        "universeId": "u1",
        "enabled": True,
        "protocol": "dmxUsb",
        "device": {"driver": "enttecOpen", "port": "/dev/ttyUSB0"},
        "refreshHz": 40,
    }
    routes, notices = build_routes(
        settings(
            sacn_route("r1", universe_id="u2", universe=5),
            sacn_route("r2", enabled=False),
            artnet_route("r3", universe_id="u2", address=(0, 1, 2)),
            dmx_usb,
            sacn_route("r5", destination={"kind": "multicast", "iface": "no-such-if0"}),
            sacn_route("r6", destination={"kind": "multicast", "iface": "lo"}, priority=50),
            artnet_route("r7", destination={"kind": "broadcast", "iface": "no-such-if0"}),
        ),
        (STAGE, SIDE),
        artnet=network,
    )
    try:
        assert [(r.id, r.row, r.label, r.description) for r in routes] == [
            ("r1", 1, "sACN r1", "U2 Side → universe 5, unicast 127.0.0.1, priority 100"),
            ("r3", 1, "Art-Net r3", "U2 Side → port address 0.1.2, unicast 127.0.0.1"),
            (
                "r6",
                0,
                "sACN r6",
                "U1 Stage → universe 1, multicast 239.255.0.1 via lo, priority 50",
            ),
        ]
        available = ", ".join(name for _, name in socket.if_nameindex())
        assert notices == [
            RouteNotice(text="sACN r2: disabled", failed=False),
            RouteNotice(
                text="DMX-USB r4: ignored (Open DMX USB needs host-timed breaks; "
                "use an Enttec Pro or DMXking interface)",
                failed=False,
            ),
            RouteNotice(
                text="sACN r5: cannot open: no network interface 'no-such-if0' "
                f"(available: {available})",
                failed=True,
            ),
            RouteNotice(
                text="Art-Net r7: cannot open: no network interface 'no-such-if0' "
                f"(available: {available})",
                failed=True,
            ),
        ]
    finally:
        close(routes)
    assert network.local_port is None  # closing the last Art-Net route closed the socket


def test_art_net_routes_send_changes_at_once_and_keep_alives_every_second(
    artnet_receiver: ArtNetReceiver,
) -> None:
    network = ArtNetNetwork(port=0)
    routes, notices = build_routes(
        settings(artnet_route("r1"), artnet_route("r2", universe_id="u2", address=(0, 0, 1))),
        (STAGE, SIDE),
        artnet=network,
    )
    assert notices == []
    source = Source(frame(0, A, B))
    output = OutputScheduler(source, routes, FakeClock(), artnet=network)
    output.service(0.0)  # the first frame: both
    output.service(CYCLE)  # unchanged: nothing (no repeats, unlike sACN)
    source.latest = frame(1, C, B)
    output.service(2 * CYCLE)  # only u1 changed
    output.service(1.0)  # u2's keep-alive, 1 s after its first packet
    output.service(2 * CYCLE + 1.0)  # u1's keep-alive
    output.close()
    assert [(p.address, p.sequence, p.data) for p in artnet_receiver.drain()] == [
        ("0.0.0", 1, A),
        ("0.0.1", 1, B),
        ("0.0.0", 2, C),
        ("0.0.1", 2, B),
        ("0.0.0", 3, C),
    ]
    assert network.local_port is None  # the scheduler's close released the socket


def test_build_routes_reports_a_taken_art_net_port_after_the_routes(
    artnet_receiver: ArtNetReceiver,
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:  # another Art-Net program
        other.bind(("", 0))
        taken = other.getsockname()[1]
        network = ArtNetNetwork(port=taken)
        routes, notices = build_routes(
            settings(artnet_route("r1"), sacn_route("r2", enabled=False)),
            (STAGE,),
            artnet=network,
        )
        try:
            assert [r.id for r in routes] == ["r1"]
            assert [n.text.split(":")[0] for n in notices] == ["sACN r2", "Art-Net"]
            assert notices[1].failed
            assert notices[1].text.startswith(f"Art-Net: cannot listen on UDP port {taken} ")
            assert network.notices == []  # taken by build_routes
        finally:
            close(routes)


def test_routes_sending_one_universe_share_its_sequence(receiver: Receiver) -> None:
    routes, _ = build_routes(
        settings(sacn_route("main", priority=100), sacn_route("backup", priority=50)), (STAGE,)
    )
    output = scheduler(Source(frame(1, A)), *routes)
    output.service(0.0)
    output.service(CYCLE)
    output.close()
    data = [(p.priority, p.sequence) for p in receiver.drain() if not p.terminated]
    assert data == [(100, 0), (50, 1), (100, 2), (50, 3)]


def test_a_stalled_engine_sends_keep_alives_of_the_last_frame(receiver: Receiver) -> None:
    routes, _ = build_routes(settings(sacn_route("r1")), (STAGE,))
    output = scheduler(Source(frame(1, A)), *routes)
    for k in range(int(2 * OUTPUT_HZ)):  # two seconds without a new frame
        output.service(k * CYCLE)
    output.close()
    packets = receiver.drain()
    data = [p for p in packets if not p.terminated]
    # The first frame, three repeats, then a keep-alive every 40 cycles.
    assert [p.sequence for p in data] == [0, 1, 2, 3, 4, 5]
    assert {p.data for p in data} == {A}
    assert {p.cid for p in packets} == {uuid.UUID(CID)}
    assert [p.sequence for p in packets if p.terminated] == [6, 7, 8]
