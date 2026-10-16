"""The surface manager (phase-6-plan §5.13): surfaces open, change and close
as live edits change the show, and a surface that cannot open is reported
once."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest

from busk.compiler.compile import CompiledShow
from busk.io import midi
from busk.io.surfaces import SurfaceManager
from busk.model.surface import ControlSurface
from busk.process.report import say, warn

NANO = "nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0"
APC = "APC40 mkII:APC40 mkII MIDI 1 24:0"
PORTS = ["Midi Through:Midi Through Port-0 14:0", NANO, APC]


def midi_surface(ident: str, device: str) -> ControlSurface:
    return cast(
        ControlSurface,
        {
            "id": ident,
            "name": ident,
            "kind": "midi",
            "match": {"deviceName": device},
            "faderPickup": "jump",
        },
    )


def show(*surfaces: ControlSurface) -> CompiledShow:
    """A compiled show as the manager sees it: a fresh surfaces tuple, as
    every compile makes."""
    return cast(CompiledShow, SimpleNamespace(surfaces=tuple(surfaces)))


class FakePort:
    def __init__(self, name: str, callback: Callable[[Any], None]) -> None:
        self.name, self.callback, self.closed = name, callback, 0

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[FakePort]:
    """Fake MIDI ports: :data:`PORTS` exist, and every port opened is recorded."""
    ports: list[FakePort] = []

    def open_input(name: str, callback: Callable[[Any], None]) -> FakePort:
        ports.append(FakePort(name, callback))
        return ports[-1]

    monkeypatch.setattr(midi, "input_names", lambda: list(PORTS))
    monkeypatch.setattr(midi.mido, "open_input", open_input)
    return ports


def test_open_change_and_close(opened: list[FakePort], capsys: pytest.CaptureFixture[str]) -> None:
    manager = SurfaceManager(lambda event: None, say=say, warn=warn)
    nano, apc = midi_surface("s-a", "nanoKONTROL2"), midi_surface("s-b", "APC40")
    manager.reconcile(show(nano, apc))
    assert [port.name for port in opened] == [NANO, APC]
    assert capsys.readouterr().out == f"MIDI s-a: {NANO}\nMIDI s-b: {APC}\n"

    manager.reconcile(show(nano, apc))  # an edit elsewhere: nothing reopens
    assert len(opened) == 2

    manager.reconcile(show(midi_surface("s-a", "APC40"), apc))  # s-a changed device
    assert (opened[0].closed, opened[1].closed) == (1, 0)
    assert opened[2].name == APC

    manager.reconcile(show(apc))  # s-a removed
    assert (opened[2].closed, opened[1].closed) == (1, 0)

    manager.close()
    assert opened[1].closed == 1
    manager.reconcile(show(nano))  # closed: nothing opens again
    assert len(opened) == 3


def test_a_missing_device_is_reported_once(
    opened: list[FakePort], capsys: pytest.CaptureFixture[str]
) -> None:
    manager = SurfaceManager(lambda event: None, say=say, warn=warn)
    missing = midi_surface("s-x", "Launchpad")
    for _ in range(3):
        manager.reconcile(show(missing))
    assert opened == []
    assert capsys.readouterr().err == (
        f"MIDI s-x: 'Launchpad' not found; available: {', '.join(PORTS)}\n"
    )
    manager.reconcile(show(midi_surface("s-x", "nano")))  # an edit fixes the name
    assert [port.name for port in opened] == [NANO]


def test_a_backend_that_cannot_run_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> list[str]:
        raise OSError("no ALSA sequencer")

    monkeypatch.setattr(midi, "input_names", broken)
    manager = SurfaceManager(lambda event: None, say=say, warn=warn)
    manager.reconcile(show(midi_surface("s-a", "nano")))
    assert capsys.readouterr().err == "MIDI s-a: unavailable: no ALSA sequencer\n"


def test_events_reach_the_handler(opened: list[FakePort]) -> None:
    events: list[Any] = []
    manager = SurfaceManager(events.append, say=say, warn=warn)
    manager.reconcile(show(midi_surface("s-a", "nano")))
    opened[0].callback(midi.mido.Message("control_change", channel=0, control=3, value=127))
    assert [(e.surfaceId, e.address, e.value) for e in events] == [
        ("s-a", {"kind": "midiCC", "channel": 1, "cc": 3}, 1.0)
    ]


def test_a_web_surface_needs_the_engine(
    opened: list[FakePort], capsys: pytest.CaptureFixture[str]
) -> None:
    """Web surfaces open with a link to the engine (tests/test_web_api.py);
    a manager made without one reports them."""
    web = cast(
        ControlSurface,
        {"id": "s-w", "name": "w", "kind": "web", "match": {"port": 8080}, "faderPickup": "jump"},
    )
    manager = SurfaceManager(lambda event: None, say=say, warn=warn)
    manager.reconcile(show(web))
    assert opened == []
    assert manager.senders() == {}
    assert capsys.readouterr().err == "Web s-w: unavailable: no engine to serve\n"
