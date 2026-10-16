"""MIDI: message translation, MIDI clock beats, port matching, the callback
guard, feedback encoding and output ports, and end-to-end runs through
virtual ALSA ports (``midi`` marker)."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import mido
import pytest

from builders import compile_doc
from busk.commands.bus import CommandBus
from busk.engine.clock import FakeClock
from busk.io import midi
from busk.io.bindings import BindingResolver
from busk.io.events import InputEvent
from busk.io.midi import BeatCounter, MidiInput, MidiOutput, encode, translate
from busk.model.common import SurfaceId
from busk.model.show import Show
from busk.model.surface import ControlSurface

S = SurfaceId("s")


@pytest.mark.parametrize(
    ("message", "address", "value"),
    [
        (
            mido.Message("control_change", channel=0, control=7, value=127),
            {"kind": "midiCC", "channel": 1, "cc": 7},
            1.0,
        ),
        (
            mido.Message("control_change", channel=15, control=0, value=0),
            {"kind": "midiCC", "channel": 16, "cc": 0},
            0.0,
        ),
        (
            mido.Message("note_on", channel=1, note=32, velocity=1),
            {"kind": "midiNote", "channel": 2, "note": 32},
            1.0,
        ),
        (
            mido.Message("note_on", channel=1, note=32, velocity=0),  # running-status note off
            {"kind": "midiNote", "channel": 2, "note": 32},
            0.0,
        ),
        (
            mido.Message("note_off", channel=1, note=32, velocity=64),
            {"kind": "midiNote", "channel": 2, "note": 32},
            0.0,
        ),
        (
            mido.Message("pitchwheel", channel=2, pitch=-8192),
            {"kind": "midiPitchBend", "channel": 3},
            0.0,
        ),
        (
            mido.Message("pitchwheel", channel=2, pitch=8191),
            {"kind": "midiPitchBend", "channel": 3},
            1.0,
        ),
    ],
)
def test_translate(message: Any, address: dict[str, Any], value: float) -> None:
    assert translate(S, message) == InputEvent(S, cast(Any, address), value)


def test_pitch_bend_centre() -> None:
    event = translate(S, mido.Message("pitchwheel", pitch=0))
    assert event is not None
    assert event.value == pytest.approx(0.5, abs=1e-4)


@pytest.mark.parametrize(
    "message",
    [
        mido.Message("clock"),
        mido.Message("program_change", program=3),
        mido.Message("sysex", data=[1]),
    ],
)
def test_other_messages_are_ignored(message: Any) -> None:
    assert translate(S, message) is None


# ------------------------------------------------------------- MIDI clock

CLOCK = {"kind": "midiClock"}


def beats_of(messages: list[Any], beats: BeatCounter | None = None) -> list[tuple[int, float]]:
    """(index of the message, value) of every clock event ``messages`` give."""
    counter = BeatCounter() if beats is None else beats
    found = []
    for k, message in enumerate(messages):
        event = translate(S, message, counter)
        if event is not None:
            assert event.address == CLOCK
            found.append((k, event.value))
    return found


def test_a_press_every_24_clocks() -> None:
    """The first clock starts a beat: pressed on it, released on the next."""
    clocks = [mido.Message("clock")] * 72
    assert beats_of(clocks) == [(0, 1.0), (1, 0.0), (24, 1.0), (25, 0.0), (48, 1.0), (49, 0.0)]


def test_start_makes_the_next_clock_a_downbeat() -> None:
    messages = [*[mido.Message("clock")] * 10, mido.Message("start"), *[mido.Message("clock")] * 2]
    assert beats_of(messages) == [(0, 1.0), (1, 0.0), (11, 1.0), (12, 0.0)]


def test_song_position_moves_the_count() -> None:
    """Position 6 sixteenths is 36 clocks: half a beat, so the beat after it
    comes 12 clocks later. Position 8 is a beat: its first clock presses."""
    beats = BeatCounter()
    beats_of([mido.Message("clock")] * 5, beats)
    moved = [mido.Message("songpos", pos=6), *[mido.Message("clock")] * 14]
    assert beats_of(moved, beats) == [(13, 1.0), (14, 0.0)]
    on_beat = [mido.Message("songpos", pos=8), mido.Message("clock"), mido.Message("clock")]
    assert beats_of(on_beat, beats) == [(1, 1.0), (2, 0.0)]


@pytest.mark.parametrize("message", [mido.Message("stop"), mido.Message("continue")])
def test_stop_and_continue_keep_the_count(message: Any) -> None:
    messages = [*[mido.Message("clock")] * 3, message, *[mido.Message("clock")] * 22]
    assert beats_of(messages) == [(0, 1.0), (1, 0.0), (25, 1.0)]


def test_each_input_counts_its_own_clocks(opened: list[FakePort]) -> None:
    events: list[InputEvent] = []
    first, second = (
        MidiInput(surface("nano"), events.append),
        MidiInput(surface("nano"), events.append),
    )
    first.open(NAMES)
    second.open(NAMES)
    for _ in range(3):
        opened[0].callback(mido.Message("clock"))
    opened[1].callback(mido.Message("clock"))
    assert [event.value for event in events] == [1.0, 0.0, 1.0]


def surface(device: str | None) -> ControlSurface:
    match = {} if device is None else {"deviceName": device}
    return cast(
        ControlSurface,
        {"id": "s", "name": "S", "kind": "midi", "match": match, "faderPickup": "jump"},
    )


NAMES = ["Midi Through:Midi Through Port-0 14:0", "nanoKONTROL2:nanoKONTROL2 _ CTRL 20:0"]


class FakePort:
    def __init__(self, name: str, callback: Callable[[Any], None]) -> None:
        self.name, self.callback, self.closed = name, callback, 0

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[FakePort]:
    """Replace ``mido.open_input`` with a fake that records the ports it opens."""
    ports: list[FakePort] = []

    def open_input(name: str, callback: Callable[[Any], None]) -> FakePort:
        ports.append(FakePort(name, callback))
        return ports[-1]

    monkeypatch.setattr(midi.mido, "open_input", open_input)
    return ports


def test_the_first_port_containing_the_device_name_opens(opened: list[FakePort]) -> None:
    port = MidiInput(surface("NANOkontrol2"), lambda event: None)
    assert port.open(NAMES) == NAMES[1]  # case-insensitive
    assert [p.name for p in opened] == [NAMES[1]]
    port.close()
    port.close()  # idempotent
    assert opened[0].closed == 1


@pytest.mark.parametrize("device", ["APC40", "", None])
def test_no_match_opens_nothing(opened: list[FakePort], device: str | None) -> None:
    assert MidiInput(surface(device), lambda event: None).open(NAMES) is None
    assert opened == []


def test_the_callback_translates_and_never_raises(opened: list[FakePort]) -> None:
    events: list[InputEvent] = []

    def on_event(event: InputEvent) -> None:
        events.append(event)
        if event.value == 0.0:
            raise RuntimeError("binding bug")

    port = MidiInput(surface("nano"), on_event)
    port.open(NAMES)
    callback = opened[0].callback
    callback(mido.Message("control_change", control=1, value=127))
    callback(mido.Message("program_change", program=3))  # ignored
    callback(mido.Message("control_change", control=1, value=0))  # raises inside: swallowed
    assert [event.value for event in events] == [1.0, 0.0]
    assert port.errors == 1


# ------------------------------------------------------------- output

CC = {"kind": "midiCC", "channel": 2, "cc": 7}
NOTE = {"kind": "midiNote", "channel": 16, "note": 60}
BEND = {"kind": "midiPitchBend", "channel": 1}


@pytest.mark.parametrize(
    ("address", "kind", "value", "expected"),
    [
        (CC, "led", 1.0, mido.Message("control_change", channel=1, control=7, value=127)),
        (CC, "led", 0.0, mido.Message("control_change", channel=1, control=7, value=0)),
        (CC, "motorFader", 0.5, mido.Message("control_change", channel=1, control=7, value=64)),
        (CC, "motorFader", 1.0, mido.Message("control_change", channel=1, control=7, value=127)),
        (NOTE, "led", 1.0, mido.Message("note_on", channel=15, note=60, velocity=127)),
        (NOTE, "led", 0.0, mido.Message("note_off", channel=15, note=60)),
        (NOTE, "motorFader", 0.25, mido.Message("note_on", channel=15, note=60, velocity=32)),
        (BEND, "motorFader", 0.0, mido.Message("pitchwheel", channel=0, pitch=-8192)),
        (BEND, "motorFader", 1.0, mido.Message("pitchwheel", channel=0, pitch=8191)),
        (BEND, "motorFader", 0.5, mido.Message("pitchwheel", channel=0, pitch=0)),
        (BEND, "led", 1.0, None),  # a pitch bend has no LED
        (CC, "display", 1.0, None),  # MIDI shows no text
        (CLOCK, "led", 1.0, None),
        ({"kind": "osc", "path": "/x"}, "led", 1.0, None),
        ({"kind": "hw", "controlId": "f1"}, "motorFader", 1.0, None),
    ],
)
def test_encode(address: Any, kind: Any, value: float, expected: Any) -> None:
    assert encode(address, kind, value) == expected


def test_a_motor_fader_round_trips_through_translate() -> None:
    """What a motor fader is sent is what it would send back."""
    for value in (0.0, 0.3, 0.5, 0.77, 1.0):
        for address in (CC, NOTE, BEND):
            event = translate(S, encode(address, "motorFader", value))
            if address is NOTE:
                continue  # a note's input is a button: any velocity presses
            assert event is not None
            assert event.value == pytest.approx(value, abs=0.5 / 127)


class FakeOutput:
    def __init__(self, name: str) -> None:
        self.name, self.sent, self.closed = name, [], 0

    def send(self, message: Any) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed += 1


def test_the_first_output_port_containing_the_device_name_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs: list[FakeOutput] = []

    def open_output(name: str) -> FakeOutput:
        outputs.append(FakeOutput(name))
        return outputs[-1]

    monkeypatch.setattr(midi.mido, "open_output", open_output)
    port = MidiOutput(surface("NANOKONTROL2"))
    for device in ("APC40", "", None):  # no match, and no name at all
        assert MidiOutput(surface(device)).open(NAMES) is None
    assert port.open(NAMES) == NAMES[1]
    port.send(cast(Any, CC), "led", 1.0)
    port.send(cast(Any, CC), "display", 1.0)  # nothing to send
    assert outputs[0].sent == [mido.Message("control_change", channel=1, control=7, value=127)]
    port.close()
    port.close()  # idempotent
    port.send(cast(Any, CC), "led", 0.0)  # closed: dropped
    assert (outputs[0].closed, len(outputs[0].sent)) == (1, 1)


# ------------------------------------------------------- virtual ALSA port


def sequencer_available() -> bool:
    seq = Path("/dev/snd/seq")
    return seq.exists() and os.access(seq, os.R_OK | os.W_OK)


@pytest.mark.midi
@pytest.mark.skipif(not sequencer_available(), reason="needs an ALSA sequencer (/dev/snd/seq)")
def test_a_fader_cc_through_a_virtual_port_reaches_the_bus(appendix_a: dict[str, Any]) -> None:
    name = f"busk-test-{uuid.uuid4().hex[:8]}"
    appendix_a["surfaces"][0]["match"] = {"deviceName": name}
    compiled = compile_doc(appendix_a)
    bus = CommandBus(compiled, FakeClock())
    resolver = BindingResolver(cast(Show, appendix_a), compiled, bus)
    with mido.open_output(name, virtual=True) as device:
        port = MidiInput(appendix_a["surfaces"][0], resolver.handle)
        assert port.open() is not None
        try:
            time.sleep(0.05)  # let the sequencer connect the ports
            device.send(mido.Message("control_change", channel=0, control=0, value=127))  # b1
            commands: list[Any] = []
            deadline = time.monotonic() + 2.0
            while not commands and time.monotonic() < deadline:
                commands = [envelope["command"] for envelope in bus.drain()]
                time.sleep(0.01)
        finally:
            port.close()
    assert commands == [{"type": "SET_FADER", "slot": 0, "level": 1.0}]


def wait_for(drain: Callable[[], list[Any]], count: int) -> list[Any]:
    """Collect what ``drain`` returns until ``count`` items came, or 2 s passed."""
    found: list[Any] = []
    deadline = time.monotonic() + 2.0
    while len(found) < count and time.monotonic() < deadline:
        found += drain()
        time.sleep(0.01)
    return found


@pytest.mark.midi
@pytest.mark.skipif(not sequencer_available(), reason="needs an ALSA sequencer (/dev/snd/seq)")
def test_clocks_through_a_virtual_port_tap_the_speed_master(appendix_a: dict[str, Any]) -> None:
    """mido's rtmidi backend delivers timing messages (rtmidi filters them by
    default): two beats of clock tap twice, then a fader CC follows."""
    name = f"busk-test-{uuid.uuid4().hex[:8]}"
    appendix_a["surfaces"][0]["match"] = {"deviceName": name}
    appendix_a["bindings"].append(
        {"id": "b-clock", "surfaceId": "s-midi", "input": {"kind": "midiClock"},
         "action": {"kind": "tap", "masterId": "m-speed"}}
    )  # fmt: skip
    compiled = compile_doc(appendix_a)
    bus = CommandBus(compiled, FakeClock())
    resolver = BindingResolver(cast(Show, appendix_a), compiled, bus)
    with mido.open_output(name, virtual=True) as device:
        port = MidiInput(appendix_a["surfaces"][0], resolver.handle)
        assert port.open() is not None
        try:
            time.sleep(0.05)  # let the sequencer connect the ports
            device.send(mido.Message("start"))
            for _ in range(2 * 24):
                device.send(mido.Message("clock"))
            device.send(mido.Message("control_change", channel=0, control=0, value=127))  # b1
            commands = wait_for(lambda: [e["command"] for e in bus.drain()], 3)
        finally:
            port.close()
    tap = {"type": "TAP", "masterId": "m-speed"}
    assert commands == [tap, tap, {"type": "SET_FADER", "slot": 0, "level": 1.0}]


@pytest.mark.midi
@pytest.mark.skipif(not sequencer_available(), reason="needs an ALSA sequencer (/dev/snd/seq)")
def test_feedback_through_a_virtual_port() -> None:
    """A MidiOutput finds a device's input port by name and sends to it."""
    name = f"busk-test-{uuid.uuid4().hex[:8]}"
    received: list[Any] = []
    with mido.open_input(name, virtual=True, callback=received.append):
        port = MidiOutput(surface(name))
        assert port.open() is not None
        try:
            time.sleep(0.05)
            port.send(cast(Any, CC), "motorFader", 0.5)
            port.send(cast(Any, NOTE), "led", 1.0)
            deadline = time.monotonic() + 2.0
            while len(received) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            port.close()
    assert received == [
        mido.Message("control_change", channel=1, control=7, value=64),
        mido.Message("note_on", channel=15, note=60, velocity=127),
    ]
