"""``LiveShow``: a show in real time inside the caller's process
(phase-8-plan §5.5, step 7).

Real sACN goes to a receiver on localhost, a real OSC surface takes a
message and sends its feedback back, and start and stop leave nothing
behind: no thread, no process-wide setting, no print (everything is
logged).
"""

from __future__ import annotations

import gc
import logging
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from builders import localhost_route
from busk.engine.clock import SWITCH_INTERVAL
from busk.io import midi
from busk.io.osc import decode, encode
from busk.model.show import Show
from busk.persistence.show_file import load_show
from busk.runner import LiveShow
from sacn_receiver import Receiver

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture(autouse=True)
def no_midi_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    """No MIDI port, whatever is plugged in: the Phase 3 show's nanoKONTROL2
    surface stays closed."""
    monkeypatch.setattr(midi, "input_names", list)
    monkeypatch.setattr(midi, "output_names", list)


@pytest.fixture
def phase3() -> Show:
    """The Phase 3 show, its sACN routes sending to 127.0.0.1."""
    show, _ = load_show(GOLDEN / "phase3_built_show.json")
    return cast(Show, localhost_route(cast(dict[str, Any], show)))


@pytest.fixture
def client() -> Iterator[socket.socket]:
    """A UDP socket on an ephemeral localhost port, as a phone app would be."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    yield sock
    sock.close()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def eventually(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def busk_threads() -> list[str]:
    return [thread.name for thread in threading.enumerate() if thread.name.startswith("busk-")]


# ---------------------------------------------------------------- output


def test_routes_send_the_universes_and_terminate_on_stop(
    phase3: Show,
    receiver: Receiver,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.INFO, logger="busk")
    with LiveShow(phase3) as live:
        assert live.snapshot is not None  # start() waited for the first snapshot
        assert live.execute("fader 1 1").ok
        eventually(lambda: live.frame is not None and live.frame.universes[1][8] == 204)
        packet = receiver.receive()
        while packet.data[8] != 204:  # the frames sent before the fader
            packet = receiver.receive()
        assert packet.universe == 1
        frame = live.frame
        assert frame is not None
        assert list(frame.universes) == [1]
    packets = receiver.drain()
    assert packets
    assert packets[-1].terminated
    assert any(r.name == "busk.output" and "sACN" in r.getMessage() for r in caplog.records)
    assert capsys.readouterr() == ("", "")


def test_without_output_no_route_opens(phase3: Show, receiver: Receiver) -> None:
    with LiveShow(phase3, output=False) as live:
        assert live.execute("fader 1 1").ok
        eventually(lambda: live.frame is not None and live.frame.universes[1][8] == 204)
    assert receiver.drain() == []


# -------------------------------------------------------------- surfaces


def test_an_osc_surface_drives_the_show_and_gets_feedback(
    phase3: Show, client: socket.socket, capsys: pytest.CaptureFixture[str]
) -> None:
    port = free_port()
    feedback = client.getsockname()[1]
    with LiveShow(phase3, surfaces=True) as live:
        for line in (
            f'surface add osc "Phone" port {port} feedback 127.0.0.1:{feedback}',
            'bind "Phone" osc "/gm" master gm motor',
        ):
            assert live.execute(line).ok, line
        eventually(lambda: _sent(client, port, encode("/gm", 0.25), live))
        echoed = [args for address, args in decode(client.recv(1024)) if address == "/gm"]
        while not echoed or echoed[-1] != (0.25,):  # the motor follows the grand master
            echoed = [args for address, args in decode(client.recv(1024)) if address == "/gm"]
    assert capsys.readouterr() == ("", "")


def _sent(client: socket.socket, port: int, packet: bytes, live: LiveShow) -> bool:
    """Send ``packet`` to the surface (again, until it has opened) and say
    whether the grand master followed."""
    client.sendto(packet, ("127.0.0.1", port))
    time.sleep(0.05)
    return live.snapshot is not None and live.snapshot.grandMaster == 0.25


def test_surfaces_are_off_unless_asked(phase3: Show) -> None:
    port = free_port()
    with LiveShow(phase3) as live:
        assert live.execute(f'surface add osc "Phone" port {port}').ok
        time.sleep(0.3)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", port))  # nobody listens there


# ------------------------------------------------------- start and stop


def test_an_exception_in_the_block_still_stops_everything(phase3: Show, receiver: Receiver) -> None:
    running: list[str] = []

    def fails() -> None:
        with LiveShow(phase3, surfaces=True):
            running.extend(busk_threads())
            _ = 1 / 0

    with pytest.raises(ZeroDivisionError):
        fails()
    assert running
    assert busk_threads() == []
    packets = receiver.drain()
    assert packets
    assert packets[-1].terminated


def test_start_twice_raises_and_stop_twice_is_fine(phase3: Show) -> None:
    live = LiveShow(phase3, output=False)
    live.stop()  # before start: nothing to stop
    live.start()
    try:
        with pytest.raises(RuntimeError):
            live.start()
    finally:
        live.stop()
    live.stop()
    assert busk_threads() == []
    with pytest.raises(RuntimeError):
        live.start()  # a LiveShow runs once


def test_no_process_wide_changes_unless_asked(phase3: Show) -> None:
    interval, frozen = sys.getswitchinterval(), gc.get_freeze_count()
    with LiveShow(phase3, output=False):
        assert sys.getswitchinterval() == interval
        assert gc.get_freeze_count() == frozen
    with LiveShow(phase3, output=False, tune_interpreter=True):
        assert sys.getswitchinterval() == pytest.approx(SWITCH_INTERVAL)
    assert sys.getswitchinterval() == interval
    assert gc.get_freeze_count() == frozen


def test_commands_before_start_apply_once_it_runs(phase3: Show) -> None:
    live = LiveShow(phase3, output=False)
    assert live.snapshot is None
    assert live.frame is None
    assert live.execute("fader 1 1").ok
    with live:
        eventually(lambda: live.frame is not None and live.frame.universes[1][8] == 204)


def test_the_web_key_comes_from_the_state_dir_when_given(
    phase3: Show, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="busk")
    port = free_port()
    with LiveShow(phase3, output=False, surfaces=True, state_dir=tmp_path) as live:
        assert live.execute(f'surface add web "Phone" port {port} on 127.0.0.1').ok
        eventually(lambda: any("?k=" in r.getMessage() for r in caplog.records))
    key = (tmp_path / "web-key").read_text().strip()
    assert any(key in r.getMessage() for r in caplog.records if r.name == "busk.surfaces")
