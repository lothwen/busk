"""The control surfaces' status (GAP-08 of ``docs/dev/tui/engine-gaps.md``).

``LiveShow.surfaces`` lists every control surface of the show, in show
order, with what it does: ``ok`` (open; a web remote with its addresses),
``failed`` and why, as its line said, or ``ignored`` (``hid`` and
``internal``). The surface manager publishes the table whole, and only when
it changed (``SurfaceManager.status``). ``busk run``'s console process opens
the surfaces, so its show has them too.

The manager tests use fake MIDI ports (:class:`test_hotplug.Ports`) and real
OSC and web sockets on localhost.
"""

from __future__ import annotations

import copy
import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from busk.compiler.compile import CompiledShow, compile_show
from busk.engine.clock import FakeClock
from busk.engine.link import LocalEngine
from busk.engine.loop import Engine
from busk.io import midi
from busk.io.surfaces import UNPLUGGED, SurfaceManager, SurfaceStatus
from busk.model.show import Show
from busk.model.surface import ControlSurface
from busk.persistence.show_file import load_show
from busk.runner import LiveShow
from busk.session.library import ProfileLibrary
from busk.session.session import CommandResult
from busk.web.api import WebLink
from test_hotplug import NANO, THROUGH, Ports

GOLDEN = Path(__file__).parent / "golden"
KEY = "Qx7f2LmA"
NANO_ID = "s-00000000002f"  # the Phase 3 show's nanoKONTROL2
NANO_MISSING = "'nanoKONTROL2' not found; available: none"


# ------------------------------------------------------------------ helpers


def surface(ident: str, kind: str, name: str | None = None, **match: Any) -> ControlSurface:
    return cast(
        ControlSurface,
        {
            "id": ident,
            "name": name or ident,
            "kind": kind,
            "match": match,
            "faderPickup": "jump",
        },
    )


def show(*surfaces: ControlSurface) -> CompiledShow:
    """A compiled show as the manager sees it: a fresh surfaces tuple, as
    every compile makes."""
    return cast(CompiledShow, SimpleNamespace(surfaces=tuple(surfaces)))


def states(manager: SurfaceManager) -> list[tuple[str, str, str]]:
    """Each surface's id, state and detail."""
    return [(s.id, s.state, s.detail) for s in manager.status()]


@pytest.fixture
def ports(monkeypatch: pytest.MonkeyPatch) -> Ports:
    """Fake MIDI inputs: only Midi Through until a test plugs more in."""
    system = Ports()
    monkeypatch.setattr(midi, "input_names", system.list)
    monkeypatch.setattr(midi.mido, "open_input", system.open_input)
    return system


@pytest.fixture
def lines() -> dict[str, list[str]]:
    """What the manager says and warns, by ``say`` and ``warn``."""
    return {"say": [], "warn": []}


@pytest.fixture
def manager(lines: dict[str, list[str]]) -> Iterator[SurfaceManager]:
    """A manager that can serve web surfaces, closed after the test."""
    compiled = compile_show(load_show(GOLDEN / "phase3_built_show.json")[0])
    web = WebLink(
        snapshot=lambda: None,
        compiled=lambda: compiled,
        submit=lambda command, origin: CommandResult(ok=True, message=""),
        clock=lambda: 0.0,
        key=KEY,
    )
    made = SurfaceManager(
        lambda event: None, web, say=lines["say"].append, warn=lines["warn"].append
    )
    yield made
    made.close()


def free_port(kind: socket.SocketKind) -> int:
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def taken_udp() -> Iterator[int]:
    """A UDP port another socket listens on, on every interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("", 0))
        yield sock.getsockname()[1]


@pytest.fixture
def taken_tcp() -> Iterator[int]:
    """A TCP port another server listens on, on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield sock.getsockname()[1]


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


# -------------------------------------------------------------- the manager


def test_there_is_no_status_until_the_first_reconcile(manager: SurfaceManager) -> None:
    assert manager.status() == ()


def test_every_surface_of_the_show_is_listed_in_show_order_with_what_it_does(
    manager: SurfaceManager,
    ports: Ports,
    lines: dict[str, list[str]],
    taken_udp: int,
    taken_tcp: int,
) -> None:
    ports.names.append(NANO)
    osc, web = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    manager.reconcile(
        show(
            surface("s-nano", "midi", "nanoKONTROL2", deviceName="nanoKONTROL2"),
            surface("s-pad", "midi", "Launchpad", deviceName="Launchpad"),
            surface("s-touch", "osc", "Touch", port=osc),
            surface("s-busy", "osc", "Busy", port=taken_udp),
            surface("s-hid", "hid", "Wing"),
            surface("s-phone", "web", "Phone", port=web, host="127.0.0.1"),
            surface("s-tablet", "web", "Tablet", port=taken_tcp, host="127.0.0.1"),
            surface("s-int", "internal", "Panel"),
        )
    )
    in_use = "Address already in use"
    assert manager.status() == (
        SurfaceStatus(
            id="s-nano", name="nanoKONTROL2", kind="midi", state="ok", detail="", urls=()
        ),
        SurfaceStatus(
            id="s-pad",
            name="Launchpad",
            kind="midi",
            state="failed",
            detail=f"'Launchpad' not found; available: {THROUGH}, {NANO}",
            urls=(),
        ),
        SurfaceStatus(id="s-touch", name="Touch", kind="osc", state="ok", detail="", urls=()),
        SurfaceStatus(
            id="s-busy",
            name="Busy",
            kind="osc",
            state="failed",
            detail=f"cannot listen on udp {taken_udp}: {in_use}",
            urls=(),
        ),
        SurfaceStatus(
            id="s-hid",
            name="Wing",
            kind="hid",
            state="ignored",
            detail="hid surfaces are not implemented",
            urls=(),
        ),
        SurfaceStatus(
            id="s-phone",
            name="Phone",
            kind="web",
            state="ok",
            detail="",
            urls=(f"http://127.0.0.1:{web}/?k={KEY}",),
        ),
        SurfaceStatus(
            id="s-tablet",
            name="Tablet",
            kind="web",
            state="failed",
            detail=f"cannot listen on 127.0.0.1:{taken_tcp}: {in_use}",
            urls=(),
        ),
        SurfaceStatus(
            id="s-int",
            name="Panel",
            kind="internal",
            state="ignored",
            detail="internal surfaces are not implemented",
            urls=(),
        ),
    )
    # A failure's detail is what its line said; a web remote's urls are its lines.
    labels = {"midi": "MIDI", "osc": "OSC", "web": "Web"}
    failed = [s for s in manager.status() if s.state == "failed"]
    assert lines["warn"] == [f"{labels[s.kind]} {s.id}: {s.detail}" for s in failed]
    assert f"Web s-phone: http://127.0.0.1:{web}/?k={KEY}" in lines["say"]


def test_a_midi_backend_that_cannot_run_says_why(
    manager: SurfaceManager, ports: Ports, lines: dict[str, list[str]]
) -> None:
    ports.broken = True
    manager.reconcile(show(surface("s-nano", "midi", deviceName="nanoKONTROL2")))
    reason = "unavailable: ALSA lib seq_hw.c: cannot open /dev/snd/seq"
    assert states(manager) == [("s-nano", "failed", reason)]
    assert lines["warn"] == [f"MIDI s-nano: {reason}"]


def test_a_midi_surface_follows_its_device_plugged_in_and_out(
    manager: SurfaceManager, ports: Ports
) -> None:
    manager.reconcile(show(surface("s-nano", "midi", deviceName="nanoKONTROL2")))
    missing = manager.status()
    assert states(manager) == [
        ("s-nano", "failed", f"'nanoKONTROL2' not found; available: {THROUGH}")
    ]
    manager.poll(0.0)
    assert manager.status() is missing  # nothing changed

    ports.names.append(NANO)  # plugged in
    manager.poll(2.0)
    assert states(manager) == [("s-nano", "ok", "")]
    connected = manager.status()
    manager.poll(4.0)
    assert manager.status() is connected

    ports.names.remove(NANO)  # unplugged
    manager.poll(6.0)
    assert states(manager) == [("s-nano", "failed", UNPLUGGED)]
    unplugged = manager.status()
    manager.poll(8.0)  # still missing: the same detail, the same object
    assert manager.status() is unplugged

    ports.names.append(NANO)  # back
    manager.poll(10.0)
    assert states(manager) == [("s-nano", "ok", "")]


def test_live_edits_add_change_rename_and_remove_surfaces(
    manager: SurfaceManager, taken_udp: int, taken_tcp: int
) -> None:
    osc, web = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    phone = surface("s-phone", "web", "Phone", port=web, host="127.0.0.1")
    touch = surface("s-touch", "osc", "Touch", port=osc)
    manager.reconcile(show(phone))
    urls = (f"http://127.0.0.1:{web}/?k={KEY}",)
    assert [(s.id, s.name, s.state, s.urls) for s in manager.status()] == [
        ("s-phone", "Phone", "ok", urls)
    ]

    manager.reconcile(show(touch, phone))  # added, before it in show order
    assert states(manager) == [("s-touch", "ok", ""), ("s-phone", "ok", "")]

    renamed = surface("s-phone", "web", "Stage phone", port=web, host="127.0.0.1")
    manager.reconcile(show(touch, renamed))  # still the same server, with its new name
    assert [(s.id, s.name, s.state, s.urls) for s in manager.status()] == [
        ("s-touch", "Touch", "ok", ()),
        ("s-phone", "Stage phone", "ok", urls),
    ]

    busy = surface("s-touch", "osc", "Touch", port=taken_udp)
    manager.reconcile(show(busy, renamed))  # changed to a port in use: reopened, and failed
    in_use = f"cannot listen on udp {taken_udp}: Address already in use"
    assert states(manager) == [("s-touch", "failed", in_use), ("s-phone", "ok", "")]

    manager.reconcile(show(touch, renamed))  # back to a free port: open again
    assert states(manager) == [("s-touch", "ok", ""), ("s-phone", "ok", "")]

    moved = surface("s-phone", "web", "Stage phone", port=taken_tcp, host="127.0.0.1")
    manager.reconcile(show(touch, moved))  # the remote moves to a port in use: no addresses
    in_use = f"cannot listen on 127.0.0.1:{taken_tcp}: Address already in use"
    assert [(s.id, s.state, s.detail, s.urls) for s in manager.status()] == [
        ("s-touch", "ok", "", ()),
        ("s-phone", "failed", in_use, ()),
    ]
    manager.reconcile(show(touch, renamed))
    assert manager.status()[1].urls == urls

    manager.reconcile(show(renamed))  # removed
    assert states(manager) == [("s-phone", "ok", "")]
    manager.reconcile(show())
    assert manager.status() == ()


def test_the_same_object_comes_back_while_nothing_changed(manager: SurfaceManager) -> None:
    touch = surface("s-touch", "osc", "Touch", port=free_port(socket.SOCK_DGRAM))
    manager.reconcile(show(touch, surface("s-hid", "hid")))
    status = manager.status()
    manager.reconcile(show(touch, surface("s-hid", "hid")))  # another compile, equal surfaces
    assert manager.status() is status
    reader: list[tuple[SurfaceStatus, ...]] = []
    thread = threading.Thread(target=lambda: reader.append(manager.status()))
    thread.start()
    thread.join()
    assert reader[0] is status


def test_close_leaves_the_status_as_it_ended(manager: SurfaceManager) -> None:
    touch = surface("s-touch", "osc", "Touch", port=free_port(socket.SOCK_DGRAM))
    manager.reconcile(show(touch))
    status = manager.status()
    manager.close()
    assert manager.status() is status
    manager.reconcile(show())  # closed: nothing changes any more
    assert manager.status() is status


# ---------------------------------------------------------------- LiveShow


@pytest.fixture
def no_midi_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    """No MIDI port, whatever is plugged in: the Phase 3 show's nanoKONTROL2
    surface stays closed."""
    monkeypatch.setattr(midi, "input_names", list)
    monkeypatch.setattr(midi, "output_names", list)


@pytest.fixture
def phase3() -> Show:
    show, _ = load_show(GOLDEN / "phase3_built_show.json")
    return show


def surface_id(live: LiveShow, name: str) -> str:
    return next(s["id"] for s in live.show["surfaces"] if s["name"] == name)


@pytest.mark.usefixtures("no_midi_devices")
def test_a_live_show_lists_its_surfaces_from_start_to_stop(phase3: Show) -> None:
    live = LiveShow(phase3, output=False, surfaces=True)
    assert live.surfaces is None  # nothing is open before start
    with live:
        assert live.surfaces == (
            SurfaceStatus(
                id=NANO_ID,
                name="nanoKONTROL2",
                kind="midi",
                state="failed",
                detail=NANO_MISSING,
                urls=(),
            ),
        )
        osc, web = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
        assert live.execute(f'surface add osc "Touch" port {osc}').ok
        assert live.execute(f'surface add web "Phone" port {web} on 127.0.0.1').ok
        eventually(lambda: len(live.surfaces or ()) == 3)  # the monitor follows the edits
        _, touch, phone = cast(tuple[SurfaceStatus, ...], live.surfaces)
        assert (touch.id, touch.name, touch.kind, touch.state) == (
            surface_id(live, "Touch"),
            "Touch",
            "osc",
            "ok",
        )
        assert (phone.id, phone.name, phone.kind, phone.state) == (
            surface_id(live, "Phone"),
            "Phone",
            "web",
            "ok",
        )
        [url] = phone.urls
        assert url.startswith(f"http://127.0.0.1:{web}/?k=")
        last = live.surfaces
    after = live.surfaces
    assert after is last  # stop leaves them as they ended
    assert [s.state for s in after] == ["failed", "ok", "ok"]


@pytest.mark.usefixtures("no_midi_devices")
def test_a_live_show_gives_the_same_object_while_nothing_changed(phase3: Show) -> None:
    with LiveShow(phase3, output=False, surfaces=True) as live:
        surfaces = live.surfaces
        assert surfaces is not None
        assert live.execute("gm 50%").ok
        time.sleep(0.25)  # monitor passes: nothing about the surfaces changed
        assert live.surfaces is surfaces


def test_a_live_show_without_surfaces_has_none(phase3: Show) -> None:
    live = LiveShow(phase3, output=False)
    with live:
        assert live.surfaces is None
    assert live.surfaces is None


# ------------------------------------------------------------------ busk run


@pytest.mark.usefixtures("no_midi_devices")
def test_busk_runs_show_has_the_surfaces_its_console_opened(phase3: Show, tmp_path: Path) -> None:
    doc = cast(dict[str, Any], copy.deepcopy(phase3))
    port = free_port(socket.SOCK_DGRAM)
    doc["surfaces"].append(
        {"id": "s-touch", "name": "Touch", "kind": "osc", "match": {"port": port},
         "faderPickup": "jump"}
    )  # fmt: skip
    attached = cast(Show, doc)
    compiled = compile_show(attached)
    clock = FakeClock()
    live = LiveShow._attached(
        attached,
        compiled,
        LocalEngine(Engine(compiled, clock)),
        clock,
        path=Path("unused.show"),
        library=ProfileLibrary(),
        state_dir=tmp_path,  # the web key goes there
        dirty=False,
        stamp=("s", 0),
        causes=False,
        iface="lo",
        status=lambda: "",
        about=lambda: (),
        poll=lambda: None,
        routes=lambda: None,
        say=lambda text: None,
        warn=lambda text: None,
    )
    assert live.surfaces is None
    live._open()  # what run_console does before it starts the show
    live.start()
    try:
        assert [(s.id, s.state, s.detail) for s in live.surfaces or ()] == [
            (NANO_ID, "failed", NANO_MISSING),
            ("s-touch", "ok", ""),
        ]
    finally:
        live.stop()
