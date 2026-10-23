"""The output routes' status (GAP-07 of ``docs/dev/tui/engine-gaps.md``).

``LiveShow.routes`` lists every output route of the show, in show order,
with what it does: ``ok`` (open), ``failed`` and why, ``disabled`` or
``ignored``, and its packet and error counts. The output scheduler
publishes its routes whole, so any thread reads one consistent table
(``OutputScheduler.route_status``). ``busk run --threads`` reads it in its
own process; with processes the root sends it to the console (``ROUTES``).

The scheduler tests call ``service`` with output times they choose, one
cycle at a time: fake drivers, or the real ones on localhost (the
``receiver`` fixture) with the interface lookups patched.
"""

from __future__ import annotations

import copy
import os
import socket
import sys
import threading
import time
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, NoReturn, cast

import numpy as np
import pytest

from busk.compiler.compile import CompiledUniverse, OutputLayout, compile_show
from busk.engine.clock import FakeClock, MonotonicClock
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine, Frame
from busk.model.common import UniverseId
from busk.model.output import OutputSettings
from busk.model.show import Show
from busk.output import sacn
from busk.output.driver import DriverStatus, RouteStatus
from busk.output.scheduler import OUTPUT_HZ, REOPEN_S, OutputScheduler, ScheduledRoute, build_routes
from busk.persistence.show_file import load_show
from busk.process import console_host
from busk.process.console_host import ProcessBackend, ThreadsBackend
from busk.process.options import RunOptions
from busk.process.root import Root
from busk.process.wire import Endpoint, Kind, dumps, loads, receive, send
from busk.runner import LiveShow
from busk.session.library import ProfileLibrary
from sacn_receiver import Receiver

STAGE = CompiledUniverse(id=UniverseId("u1"), number=1, name="Stage")
SIDE = CompiledUniverse(id=UniverseId("u2"), number=2, name="Side")
CYCLE = 1 / OUTPUT_HZ
CID = "0f6c1b9e-3d2a-4f7b-8e5c-1a2b3c4d5e6f"
GOLDEN = Path(__file__).parent / "golden"
OPEN_DMX = "Open DMX USB needs host-timed breaks; use an Enttec Pro or DMXking interface"


# ------------------------------------------------------------------ helpers


def sacn_route(
    route_id: str, *, universe_id: str = "u1", enabled: bool = True, **destination: str
) -> dict[str, Any]:
    return {
        "id": route_id,
        "universeId": universe_id,
        "enabled": enabled,
        "protocol": "sacn",
        "universe": int(universe_id[1:]),
        "priority": 100,
        "destination": destination or {"kind": "unicast", "host": "127.0.0.1"},
    }


def dmx_usb_route(route_id: str, port: Path, *, driver: str = "enttecPro") -> dict[str, Any]:
    return {
        "id": route_id,
        "universeId": "u1",
        "enabled": True,
        "protocol": "dmxUsb",
        "device": {"driver": driver, "port": str(port)},
        "refreshHz": 40,
    }


def layout(*routes: dict[str, Any]) -> OutputLayout:
    """The layout of a two-universe show with these routes (no dark bytes)."""
    settings = {
        "engineHz": 100,
        "sacnSourceName": "Busk Console",
        "sacnCid": CID,
        "holdLastFrameOnEngineStall": True,
        "routes": list(routes),
    }
    return OutputLayout(
        universes=(STAGE, SIDE),
        output=cast(OutputSettings, settings),
        engineHz=100.0,
        darkPositions=np.zeros(0, np.intp),
        darkValues=np.zeros(0, np.uint8),
    )


class Source:
    """Stands in for the engine: whatever frame the test puts in ``latest``."""

    def __init__(self, latest: Frame | None = None) -> None:
        self.latest = latest


def frame(seq: int, show: OutputLayout | None = None, *, on: bool = True) -> Frame:
    """A new frame whose first bytes are ``seq``, so every frame is a change."""
    data = bytes([seq % 256]) + bytes(511)
    return Frame(seq=seq, time=seq / 100, universes=(data, data), layout=show, outputEnabled=on)


def states(scheduler: OutputScheduler) -> list[tuple[str, str, str]]:
    """Each route's id, state and detail."""
    statuses = scheduler.route_status()
    assert statuses is not None
    return [(status.id, status.state, status.detail) for status in statuses]


class Fake:
    """A fake sACN driver: its status is what the test sets, and each send
    counts as a packet."""

    def __init__(self) -> None:
        self.ok = True
        self.detail = ""
        self.packets = 0
        self.errors = 0

    @property
    def protocol(self) -> Literal["sacn"]:
        return "sacn"

    def open(self) -> None:
        pass

    def send(self, data: bytes, changed: bool, now: float) -> None:
        if self.ok:
            self.packets += 1
        else:
            self.errors += 1

    def close(self) -> None:
        pass

    def status(self) -> DriverStatus:
        return DriverStatus(
            ok=self.ok, detail=self.detail, packets=self.packets, errors=self.errors
        )


@pytest.fixture
def interface(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    """``busk-test0``: an interface whose lookup fails with ``error`` until
    the test sets it to ``None``; then it is the loopback (multicast to it
    goes nowhere, but sends succeed)."""
    state: dict[str, str | None] = {"error": "no network interface 'busk-test0' (available: lo)"}
    real = socket.if_nametoindex("lo")

    def index(name: str) -> int:
        error = state["error"]
        if name == "busk-test0" and error is None:
            return real
        raise OSError(error)

    monkeypatch.setattr(sacn, "interface_index", index)
    return state


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


# ------------------------------------------------------- the scheduler's table


def test_there_is_no_status_until_a_layout_names_the_routes(receiver: Receiver) -> None:
    source = Source()
    scheduler = OutputScheduler(source, [], FakeClock())  # as the root does
    assert scheduler.route_status() is None
    scheduler.service(0.0)  # no frame yet
    assert scheduler.route_status() is None
    source.latest = frame(1, layout(sacn_route("r1")))
    scheduler.service(0.0)
    try:
        assert scheduler.route_status() == (
            RouteStatus(
                id="r1", label="sACN r1", universe=1, state="ok", detail="", packets=1, errors=0
            ),
        )
    finally:
        scheduler.close()


@pytest.mark.parametrize("opened", ["by build_routes", "by the first frame"])
def test_every_route_of_the_show_is_listed_in_show_order_with_what_it_does(
    opened: str, interface: dict[str, str | None], receiver: Receiver, tmp_path: Path
) -> None:
    """The same table whether the routes were opened before the scheduler
    (``LiveShow``, ``busk run --threads``: ``build_routes``, its notices
    passed on) or by the scheduler at the first frame (``busk run``'s root)."""
    missing = tmp_path / "ttyGONE"
    show = layout(
        sacn_route("r1", universe_id="u2"),
        sacn_route("r2", enabled=False),
        sacn_route("r3", kind="multicast", iface="busk-test0"),
        dmx_usb_route("r4", tmp_path / "ttyUSB0", driver="enttecOpen"),
        dmx_usb_route("r5", missing),
    )
    source = Source(frame(1, show))
    if opened == "by build_routes":
        routes, notices = build_routes(show.output, show.universes)
        scheduler = OutputScheduler(source, routes, FakeClock(), layout=show, notices=notices)
    else:
        scheduler = OutputScheduler(source, [], FakeClock())
    scheduler.service(0.0)
    try:
        assert scheduler.route_status() == (
            RouteStatus(
                id="r1", label="sACN r1", universe=2, state="ok", detail="", packets=1, errors=0
            ),
            RouteStatus(
                id="r2",
                label="sACN r2",
                universe=1,
                state="disabled",
                detail="",
                packets=0,
                errors=0,
            ),
            RouteStatus(
                id="r3",
                label="sACN r3",
                universe=1,
                state="failed",
                detail="no network interface 'busk-test0' (available: lo)",
                packets=0,
                errors=0,
            ),
            RouteStatus(
                id="r4",
                label="DMX-USB r4",
                universe=1,
                state="ignored",
                detail=OPEN_DMX,
                packets=0,
                errors=0,
            ),
            RouteStatus(
                id="r5",
                label="DMX-USB r5",
                universe=1,
                state="failed",
                detail=f"{missing}: No such file or directory",
                packets=0,
                errors=0,
            ),
        )
    finally:
        scheduler.close()


def test_an_open_route_has_its_drivers_state_and_counts() -> None:
    driver = Fake()
    route = ScheduledRoute(id="r1", row=0, driver=driver, description="test")
    show = layout(sacn_route("r1"))
    source = Source()
    scheduler = OutputScheduler(source, [route], FakeClock(), layout=show)
    seq = 0

    def cycle() -> tuple[str, str, int, int]:
        nonlocal seq
        seq += 1
        source.latest = frame(seq, show)
        scheduler.service(seq * CYCLE)
        [status] = cast(tuple[RouteStatus, ...], scheduler.route_status())
        return (status.state, status.detail, status.packets, status.errors)

    assert cycle() == ("ok", "", 1, 0)
    driver.ok, driver.detail = False, "[Errno 101] Network is unreachable"
    assert cycle() == ("failed", "[Errno 101] Network is unreachable", 1, 1)
    driver.ok, driver.detail = True, ""
    assert cycle() == ("ok", "", 2, 1)


def test_a_route_that_failed_to_open_shows_each_new_error_then_opens(
    interface: dict[str, str | None],
) -> None:
    show = layout(sacn_route("r1", kind="multicast", iface="busk-test0"))
    source = Source()
    scheduler = OutputScheduler(source, [], FakeClock())
    seen: list[tuple[str, str]] = []
    tables: list[object] = []  # each table published, as a reader may still hold it
    try:
        for k in range(int(5.0 / CYCLE)):
            now = k * CYCLE
            if now >= REOPEN_S:  # the retry at 2 s fails otherwise …
                interface["error"] = "[Errno 19] No such device"
            if now >= 2 * REOPEN_S:  # … and the one at 4 s opens it
                interface["error"] = None
            source.latest = frame(k + 1, show)
            scheduler.service(now)
            [(_, state, detail)] = states(scheduler)
            if not seen or seen[-1] != (state, detail):
                seen.append((state, detail))
                tables.append(scheduler._published)
    finally:
        scheduler.close()
    assert seen == [
        ("failed", "no network interface 'busk-test0' (available: lo)"),
        ("failed", "[Errno 19] No such device"),
        ("ok", ""),
    ]
    first = cast(tuple[Any, Any, Any], tables[0])
    assert first[2] == {"r1": seen[0]}  # replaced by the retries, never changed


def test_live_edits_add_change_disable_and_remove_routes(receiver: Receiver) -> None:
    source = Source()
    scheduler = OutputScheduler(source, [], FakeClock())
    seq = 0

    def show(*routes: dict[str, Any]) -> list[tuple[str, str, int]]:
        """Run two cycles with a layout of ``routes``; each route's id, state and packets."""
        nonlocal seq
        edited = layout(*routes)
        for _ in range(2):
            seq += 1
            source.latest = frame(seq, edited)
            scheduler.service(seq * CYCLE)
        statuses = scheduler.route_status()
        assert statuses is not None
        return [(status.id, status.state, status.packets) for status in statuses]

    try:
        assert show(sacn_route("r1")) == [("r1", "ok", 2)]
        assert show(sacn_route("r1"), sacn_route("r2")) == [("r1", "ok", 4), ("r2", "ok", 2)]
        moved = {**sacn_route("r1"), "priority": 50}  # changed: closed, opened again
        assert show(moved, sacn_route("r2")) == [("r1", "ok", 2), ("r2", "ok", 4)]
        assert show(moved, sacn_route("r2", enabled=False)) == [
            ("r1", "ok", 4),
            ("r2", "disabled", 0),
        ]
        assert show(sacn_route("r2", enabled=False)) == [("r2", "disabled", 0)]
    finally:
        scheduler.close()


def test_while_output_is_off_the_states_stay_and_no_packet_is_counted() -> None:
    driver = Fake()
    route = ScheduledRoute(id="r1", row=0, driver=driver, description="test")
    show = layout(sacn_route("r1"))
    source = Source()
    scheduler = OutputScheduler(source, [route], FakeClock(), layout=show)
    packets = []
    for k, on in enumerate([True, False, False, True]):
        source.latest = frame(k + 1, show, on=on)
        scheduler.service(k * CYCLE)
        [status] = cast(tuple[RouteStatus, ...], scheduler.route_status())
        packets.append((status.state, status.packets))
    assert packets == [("ok", 1), ("ok", 1), ("ok", 1), ("ok", 2)]


def test_another_thread_always_reads_one_consistent_table(receiver: Receiver) -> None:
    """Live edits switch between two layouts while another thread reads:
    every read is one of them, whole (never the routes of one with the
    definitions of the other)."""
    first = layout(sacn_route("r1"), sacn_route("r2", enabled=False))
    second = layout(sacn_route("r1", enabled=False), sacn_route("r3"))
    wanted = {
        (("r1", "ok"), ("r2", "disabled")),
        (("r1", "disabled"), ("r3", "ok")),
    }
    source = Source(frame(1, first))
    scheduler = OutputScheduler(source, [], FakeClock())
    scheduler.service(0.0)
    stop = threading.Event()
    seen: set[tuple[tuple[str, str], ...]] = set()
    failures: list[BaseException] = []

    def read() -> None:
        try:
            while not stop.is_set():
                statuses = scheduler.route_status()
                assert statuses is not None
                seen.add(tuple((status.id, status.state) for status in statuses))
        except BaseException as exc:
            failures.append(exc)

    switch = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # switch threads as often as possible
    reader = threading.Thread(target=read)
    reader.start()
    try:
        for k in range(2, 300):
            source.latest = frame(k, first if k % 2 else second)
            scheduler.service(k * CYCLE)
    finally:
        stop.set()
        reader.join()
        sys.setswitchinterval(switch)
        scheduler.close()
    assert failures == []
    assert seen
    assert seen <= wanted


# ---------------------------------------------------------------- LiveShow


@pytest.fixture
def three_routes(interface: dict[str, str | None]) -> Show:
    """The Phase 3 show with three routes: r1 sends sACN to 127.0.0.1, r2 is
    disabled, r3 sends to ``busk-test0``, which is not up."""
    show, _ = load_show(GOLDEN / "phase3_built_show.json")
    doc = cast(dict[str, Any], copy.deepcopy(show))
    [route] = doc["output"]["routes"]
    doc["output"]["routes"] = [
        {**route, "id": "r1", "destination": {"kind": "unicast", "host": "127.0.0.1"}},
        {**route, "id": "r2", "universe": 2, "enabled": False},
        {
            **route,
            "id": "r3",
            "universe": 3,
            "destination": {"kind": "multicast", "iface": "busk-test0"},
        },
    ]
    return cast(Show, doc)


NOT_UP = "no network interface 'busk-test0' (available: lo)"


def test_a_live_show_lists_its_routes_from_start_to_stop(
    three_routes: Show, receiver: Receiver
) -> None:
    live = LiveShow(three_routes)
    assert live.routes is None  # nothing is open before start
    with live:
        routes = live.routes
        assert routes is not None
        assert [(r.id, r.label, r.universe, r.state, r.detail) for r in routes] == [
            ("r1", "sACN r1", 1, "ok", ""),
            ("r2", "sACN r2", 1, "disabled", ""),
            ("r3", "sACN r3", 1, "failed", NOT_UP),
        ]
        eventually(lambda: receiver.drain() != [])
        eventually(lambda: cast(tuple[RouteStatus, ...], live.routes)[0].packets > 0)
        before = cast(tuple[RouteStatus, ...], live.routes)[0].packets
    after = cast(tuple[RouteStatus, ...], live.routes)
    assert after[0].state == "ok"
    assert after[0].packets > before  # the last frame, then Stream_Terminated
    assert live.routes is after  # nothing changes once stopped


def test_a_live_show_gives_the_same_object_while_nothing_changed(three_routes: Show) -> None:
    doc = cast(dict[str, Any], three_routes)
    for route in doc["output"]["routes"]:
        route["enabled"] = False  # nothing sends, so nothing changes
    with LiveShow(three_routes) as live:
        routes = live.routes
        assert routes is not None
        assert live.routes is routes
        reader: list[tuple[RouteStatus, ...] | None] = []
        thread = threading.Thread(target=lambda: reader.append(live.routes))
        thread.start()
        thread.join()
        assert reader[0] is routes


def test_a_live_show_without_output_has_no_routes(three_routes: Show) -> None:
    live = LiveShow(three_routes, output=False)
    with live:
        assert live.routes is None
    assert live.routes is None


# ------------------------------------------------------------------ busk run


def attached(routes: Callable[[], tuple[RouteStatus, ...] | None]) -> LiveShow:
    """``busk run``'s show, as its console makes it, with ``routes``."""
    show, _ = load_show(GOLDEN / "phase3_built_show.json")
    compiled = compile_show(show)
    clock = FakeClock()
    return LiveShow._attached(
        show,
        compiled,
        LocalEngine(Engine(compiled, clock)),
        clock,
        path=Path("unused.show"),
        library=ProfileLibrary(),
        state_dir=Path("unused"),
        dirty=False,
        stamp=("s", 0),
        causes=False,
        iface="lo",
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=routes,
        say=lambda text: None,
        warn=lambda text: None,
    )


def status(packets: int) -> RouteStatus:
    return RouteStatus(
        id="r1", label="sACN r1", universe=1, state="ok", detail="", packets=packets, errors=0
    )


def test_busk_runs_show_has_the_routes_its_backend_gives() -> None:
    given: list[tuple[RouteStatus, ...] | None] = [None]
    live = attached(lambda: given[0])
    assert live.routes is None
    given[0] = (status(3),)
    routes = live.routes
    assert routes == (status(3),)
    given[0] = (status(3),)  # an equal tuple: the one read before comes back
    assert live.routes is routes
    given[0] = (status(4),)
    assert live.routes == (status(4),)


def test_busk_run_with_threads_reads_its_own_output(
    three_routes: Show, receiver: Receiver, tmp_path: Path
) -> None:
    backend = ThreadsBackend(RunOptions(show=tmp_path / "unused.show", no_log=True))
    assert backend.routes() is None
    compiled = compile_show(three_routes)
    backend.connect(
        three_routes, compiled, None, MonotonicClock(), interactive=False, stamp=("s", 0)
    )
    backend.start()
    try:
        routes = backend.routes()
        assert routes is not None
        assert [(r.id, r.state, r.detail) for r in routes] == [
            ("r1", "ok", ""),
            ("r2", "disabled", ""),
            ("r3", "failed", NOT_UP),
        ]
    finally:
        backend.stop()


def test_the_root_sends_the_console_the_routes_when_they_change(
    receiver: Receiver, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = Root(RunOptions(show=tmp_path / "unused.show", no_log=True), [])
    ours, console = socket.socketpair()
    root._console_control = Endpoint(ours)
    console.settimeout(0.2)
    show = layout(sacn_route("r1"), sacn_route("r2", enabled=False))
    scheduler = root._scheduler

    def heard() -> list[tuple[str, str, int]]:
        """The routes of the console's next message, a ``ROUTES``."""
        message = receive(console)
        assert message is not None
        assert message.kind == Kind.ROUTES
        return [(r.id, r.state, r.packets) for r in loads(message.payload)]

    try:
        root._report_routes()  # no frame, no routes yet: nothing to say
        with pytest.raises(TimeoutError):
            receive(console)
        root._frames.latest = frame(1, show)
        scheduler.service(0.0)  # the first frame opens the routes
        root._report_routes()
        assert heard() == [("r1", "ok", 1), ("r2", "disabled", 0)]
        root._report_routes()  # nothing changed: nothing is sent
        with pytest.raises(TimeoutError):
            receive(console)
        root._frames.latest = frame(2, show)
        scheduler.service(CYCLE)
        root._report_routes()
        assert heard() == [("r1", "ok", 2), ("r2", "disabled", 0)]
    finally:
        scheduler.close()
        ours.close()
        console.close()
    assert (
        "sACN r1: U1 Stage → universe 1, unicast 127.0.0.1, priority 100" in capsys.readouterr().out
    )


class Exited(Exception):
    """What the patched ``os._exit`` raises instead of ending the test process."""


def test_the_console_process_keeps_the_routes_the_root_sent_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control link's reader, run on the test's thread: no thread is
    started, and the end of file that ends the process raises instead."""

    def exit_(code: int) -> NoReturn:
        raise Exited(code)

    started: list[str] = []
    fake = types.SimpleNamespace(
        Thread=lambda **kwargs: types.SimpleNamespace(start=lambda: started.append(kwargs["name"])),
        Lock=threading.Lock,
    )
    monkeypatch.setattr(console_host, "threading", fake)
    monkeypatch.setattr(os, "_exit", exit_)
    control, root = socket.socketpair()
    link, engine = socket.socketpair()
    try:
        backend = ProcessBackend(control, link)
        assert started == ["busk-control"]
        assert backend.routes() is None
        send(root, Kind.ROUTES, dumps((status(1),)))
        send(root, Kind.ROUTES, dumps((status(2),)))
        root.close()  # the root is gone: end of file after the two
        with pytest.raises(Exited):
            backend._read_control()
        assert backend.routes() == (status(2),)
    finally:
        for sock in (control, root, link, engine):
            sock.close()
