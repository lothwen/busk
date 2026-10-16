"""MIDI hot-plug (phase-7-plan decision 18, §5.16, step 11).

Every ``HOTPLUG_S`` the surface manager reads the MIDI input names and the
feedback worker the output names: a device that appears is opened, one whose
port name vanished is closed and waited for. The fakes here stand in for the
port-name provider and ``mido``; the last test uses a real virtual ALSA port.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import mido
import pytest

from busk.compiler.compile import CompiledShow
from busk.io import midi
from busk.io.events import InputEvent
from busk.io.surfaces import HOTPLUG_S, SurfaceManager
from busk.model.surface import ControlSurface
from test_feedback import ACTIVE, SMALL, Rig, build, snapshot

NANO = "nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0"
NANO_AGAIN = "nanoKONTROL2:nanoKONTROL2 _ CTRL 24:0"  # replugged: a new ALSA client
THROUGH = "Midi Through:Midi Through Port-0 14:0"


def test_hotplug_reads_every_two_seconds() -> None:
    assert HOTPLUG_S == 2.0


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
    return cast(CompiledShow, SimpleNamespace(surfaces=tuple(surfaces)))


class FakePort:
    def __init__(self, name: str, callback: Callable[[Any], None] | None = None) -> None:
        self.name, self.callback, self.closed = name, callback, 0
        self.sent: list[Any] = []

    def send(self, message: Any) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed += 1


class Ports:
    """The fake MIDI system: the port names it offers now (inputs and
    outputs alike) and every port opened."""

    def __init__(self) -> None:
        self.names = [THROUGH]
        self.opened: list[FakePort] = []
        self.broken = False  # listing raises, as without an ALSA sequencer

    def list(self) -> list[str]:
        if self.broken:
            raise OSError("ALSA lib seq_hw.c: cannot open /dev/snd/seq")
        return list(self.names)

    def open_input(self, name: str, callback: Callable[[Any], None]) -> FakePort:
        assert name in self.names
        self.opened.append(FakePort(name, callback))
        return self.opened[-1]

    def open_output(self, name: str) -> FakePort:
        assert name in self.names
        self.opened.append(FakePort(name))
        return self.opened[-1]


@pytest.fixture
def ports(monkeypatch: pytest.MonkeyPatch) -> Ports:
    system = Ports()
    monkeypatch.setattr(midi, "input_names", system.list)
    monkeypatch.setattr(midi, "output_names", system.list)
    monkeypatch.setattr(midi.mido, "open_input", system.open_input)
    monkeypatch.setattr(midi.mido, "open_output", system.open_output)
    return system


# ----------------------------------------------------------------- inputs


def test_a_device_appears_vanishes_and_reappears_with_each_message_once(
    ports: Ports, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[InputEvent] = []
    manager = SurfaceManager(events.append)
    manager.reconcile(show(midi_surface("s-nano", "nanoKONTROL2")))
    assert capsys.readouterr() == (
        "",
        f"MIDI s-nano: 'nanoKONTROL2' not found; available: {THROUGH}\n",
    )
    manager.poll(0.0)
    ports.names.append(NANO)  # plugged in
    manager.poll(1.0)  # not read again before HOTPLUG_S
    assert ports.opened == []
    manager.poll(2.0)
    assert capsys.readouterr() == (f"MIDI s-nano: {NANO} (connected)\n", "")
    (port,) = ports.opened
    assert port.callback is not None
    port.callback(mido.Message("control_change", channel=0, control=7, value=127))
    assert [(e.surfaceId, e.value) for e in events] == [("s-nano", 1.0)]

    manager.poll(4.0)  # still there: nothing
    ports.names.remove(NANO)  # unplugged
    manager.poll(6.0)
    manager.poll(8.0)
    assert port.closed == 1
    assert capsys.readouterr() == ("", "MIDI s-nano: unplugged; waiting for it\n")

    ports.names.append(NANO_AGAIN)  # back, under a new client number
    manager.poll(10.0)
    manager.poll(12.0)
    assert [p.name for p in ports.opened] == [NANO, NANO_AGAIN]
    assert capsys.readouterr() == (f"MIDI s-nano: {NANO_AGAIN} (connected)\n", "")
    manager.close()
    assert ports.opened[1].closed == 1


def test_a_replug_between_two_reads_reconnects_at_once(
    ports: Ports, capsys: pytest.CaptureFixture[str]
) -> None:
    ports.names.append(NANO)
    manager = SurfaceManager(lambda event: None)
    manager.reconcile(show(midi_surface("s-nano", "nanoKONTROL2")))
    manager.poll(0.0)
    ports.names[-1] = NANO_AGAIN
    manager.poll(2.0)
    assert [(p.name, p.closed) for p in ports.opened] == [(NANO, 1), (NANO_AGAIN, 0)]
    assert capsys.readouterr() == (
        f"MIDI s-nano: {NANO}\nMIDI s-nano: {NANO_AGAIN} (connected)\n",
        "MIDI s-nano: unplugged; waiting for it\n",
    )
    manager.close()


def test_a_backend_that_cannot_list_ports_is_not_reported_again(
    ports: Ports, capsys: pytest.CaptureFixture[str]
) -> None:
    ports.broken = True
    manager = SurfaceManager(lambda event: None)
    manager.reconcile(show(midi_surface("s-nano", "nanoKONTROL2")))
    assert "unavailable: ALSA lib" in capsys.readouterr().err
    for now in (0.0, 2.0, 4.0):
        manager.poll(now)
    assert capsys.readouterr() == ("", "")
    ports.broken = False  # the sequencer came back (a module loaded)
    ports.names.append(NANO)
    manager.poll(6.0)
    assert capsys.readouterr().out == f"MIDI s-nano: {NANO} (connected)\n"
    manager.close()


def test_poll_opens_nothing_after_close_or_for_other_surfaces(
    ports: Ports, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[int] = []
    ports.list = lambda: calls.append(1) or list(ports.names)  # type: ignore[method-assign]
    manager = SurfaceManager(lambda event: None)
    manager.reconcile(show())  # no MIDI surface: the names are never read
    manager.poll(0.0)
    assert calls == []
    manager.reconcile(show(midi_surface("s-nano", "nanoKONTROL2")))
    capsys.readouterr()
    manager.close()
    ports.names.append(NANO)
    manager.poll(2.0)
    assert ports.opened == []
    assert capsys.readouterr() == ("", "")


# ---------------------------------------------------------------- feedback


def test_a_reconnected_feedback_port_gets_every_value(
    ports: Ports, capsys: pytest.CaptureFixture[str]
) -> None:
    ports.names = ["nanoKONTROL2 CTRL", "Other"]
    rig = Rig(compiled=build(*SMALL))
    rig.senders = {}
    rig.snapshot = snapshot(ACTIVE)
    rig.worker.service(0.0)
    (first,) = ports.opened
    assert len(first.sent) == 2  # the LED and the motor fader (display has no MIDI)
    capsys.readouterr()

    ports.names.remove("nanoKONTROL2 CTRL")
    rig.worker.service(1.0)  # not read again yet: still sending to the old port
    rig.worker.service(2.0)
    assert first.closed == 1
    assert capsys.readouterr().err.endswith("MIDI s-midi feedback: unplugged; waiting for it\n")

    ports.names.append("nanoKONTROL2 CTRL")
    rig.worker.service(4.0)
    assert capsys.readouterr().out == "MIDI s-midi feedback: nanoKONTROL2 CTRL (connected)\n"
    second = ports.opened[-1]
    assert second is not first
    assert second.sent == first.sent  # nothing changed in the show, yet everything is sent
    rig.worker.service(4.1)
    assert len(second.sent) == 2  # and only once
    rig.worker.close()


# ---------------------------------------------------- a virtual ALSA port


def sequencer_available() -> bool:
    seq = Path("/dev/snd/seq")
    return seq.exists() and os.access(seq, os.R_OK | os.W_OK)


def wait_until(condition: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.mark.midi
@pytest.mark.skipif(not sequencer_available(), reason="needs an ALSA sequencer (/dev/snd/seq)")
def test_a_virtual_alsa_port_created_and_destroyed(capsys: pytest.CaptureFixture[str]) -> None:
    name = f"busk-hotplug-{uuid.uuid4().hex[:8]}"
    events: list[InputEvent] = []
    manager = SurfaceManager(events.append)
    manager.reconcile(show(midi_surface("s-virtual", name)))
    assert f"MIDI s-virtual: {name!r} not found" in capsys.readouterr().err
    try:
        with mido.open_output(name, virtual=True) as device:  # the device is plugged in
            manager.poll(0.0)
            out = capsys.readouterr().out
            assert out.startswith("MIDI s-virtual: ")
            assert out.endswith(" (connected)\n")
            assert name in out  # e.g. "RtMidiOut Client:busk-hotplug-… 128:0"
            time.sleep(0.05)  # let the sequencer connect the ports
            device.send(mido.Message("control_change", channel=0, control=0, value=127))
            assert wait_until(lambda: len(events) == 1)
        manager.poll(2.0)  # the device is gone
        assert capsys.readouterr() == ("", "MIDI s-virtual: unplugged; waiting for it\n")
    finally:
        manager.close()
