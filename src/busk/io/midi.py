"""MIDI: ports → input events, and feedback back out (spec §5.15; phase-2-plan
§5.11, phase-6-plan §5.9).

The backend is ``mido`` with ``python-rtmidi`` (ALSA sequencer on Linux),
behind the :class:`~busk.io.events.InputEvent` boundary so it can be swapped
(decision 16). This is the only module that imports ``mido``.

Input
-----
A :class:`MidiInput` serves one ``midi`` control surface. It opens the first
input port whose name contains ``surface.match.deviceName``, compared
case-insensitively. ALSA names look like ``nanoKONTROL2:nanoKONTROL2 _ CTRL
20:0``, so a device name matches whatever client and port numbers the
system gave it. rtmidi then calls back on its own thread with every message,
which :func:`translate` turns into an event:

=====================================  =================================================
mido message                           InputEvent
=====================================  =================================================
``control_change`` ch *c*, control *n*  ``midiCC(c+1, n)``, value / 127
``note_on`` with velocity > 0           ``midiNote(c+1, n)``, 1.0 (any velocity presses)
``note_off``, or ``note_on`` vel. 0     ``midiNote(c+1, n)``, 0.0
``pitchwheel``                          ``midiPitchBend(c+1)``, (pitch + 8192) / 16383
``clock`` on a beat (24 per beat)       ``midiClock``, 1.0, and 0.0 on the next clock
=====================================  =================================================

MIDI channels in show data are 1-based (1–16), as in Appendix A; mido's are
0-based. Other messages (sysex, program change…) are ignored.

**MIDI clock** (Phase 6, decision 13) arrives as one tap per beat: each
input counts its clocks (:class:`BeatCounter`). The clock that starts a beat
presses ``midiClock`` and the next one releases it, so a ``tap`` binding
taps once per beat. ``start`` makes the next clock a downbeat, ``songpos``
moves the count to its position (6 clocks per sixteenth), and ``stop`` and
``continue`` change nothing. mido's rtmidi backend asks rtmidi for timing
messages (``ignore_types(timing=False)``), which rtmidi filters by default.

Output
------
A :class:`MidiOutput` is the feedback port of one surface: the first
*output* port whose name contains ``match.deviceName``. :func:`encode` turns
a feedback value into a message for the binding's ``feedback.address``:

=================  ==============================  =======================================
Address            ``led`` (on above 0)            ``motorFader`` (0..1)
=================  ==============================  =======================================
``midiCC``         value 127 / 0                   value ``round(v × 127)``
``midiNote``       ``note_on`` 127 / ``note_off``  ``note_on`` velocity ``round(v × 127)``
``midiPitchBend``  —                               pitch ``round(v × 16383) − 8192``
=================  ==============================  =======================================

MIDI has no ``display`` feedback, and no other address can be sent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Literal

import mido

from busk.io.events import InputEvent
from busk.model.common import SurfaceId
from busk.model.surface import (
    ControlSurface,
    InputAddress,
    MidiCC,
    MidiClock,
    MidiNote,
    MidiPitchBend,
)

CLOCKS_PER_BEAT: Final = 24
"""MIDI clock messages per quarter note."""

_CLOCKS_PER_SIXTEENTH: Final = 6
"""A Song Position Pointer counts sixteenths: 6 clocks each."""

_MIDI_CLOCK: Final = MidiClock(kind="midiClock")

type FeedbackKind = Literal["led", "motorFader", "display"]


class BeatCounter:
    """One input's count of MIDI clocks, for :func:`translate`: the clock at
    a count divisible by 24 starts a beat."""

    def __init__(self) -> None:
        self.count = 0

    def clock(self) -> float | None:
        """Count one clock: 1.0 when it starts a beat (a press), 0.0 on the
        clock after (the release), else ``None``."""
        phase = self.count % CLOCKS_PER_BEAT
        self.count += 1
        if phase == 0:
            return 1.0
        return 0.0 if phase == 1 else None

    def start(self) -> None:
        """A Start message: the next clock is a downbeat."""
        self.count = 0

    def song_position(self, sixteenths: int) -> None:
        """A Song Position Pointer: the next clock is at ``sixteenths``."""
        self.count = _CLOCKS_PER_SIXTEENTH * sixteenths


def translate(
    surface: SurfaceId, message: Any, beats: BeatCounter | None = None
) -> InputEvent | None:
    """The input event for a mido ``message``, or ``None`` for messages
    bindings cannot address. Clock messages need the input's ``beats``
    (without one they are ignored); Start and Song Position move it."""
    kind = message.type
    if kind == "control_change":
        cc = MidiCC(kind="midiCC", channel=message.channel + 1, cc=message.control)
        return InputEvent(surface, cc, message.value / 127)
    if kind in ("note_on", "note_off"):
        pressed = kind == "note_on" and message.velocity > 0
        note = MidiNote(kind="midiNote", channel=message.channel + 1, note=message.note)
        return InputEvent(surface, note, 1.0 if pressed else 0.0)
    if kind == "pitchwheel":
        bend = MidiPitchBend(kind="midiPitchBend", channel=message.channel + 1)
        return InputEvent(surface, bend, (message.pitch + 8192) / 16383)
    if beats is not None:
        if kind == "clock":
            value = beats.clock()
            return None if value is None else InputEvent(surface, _MIDI_CLOCK, value)
        if kind == "start":
            beats.start()
        elif kind == "songpos":
            beats.song_position(message.pos)
    return None


def input_names() -> list[str]:
    """The MIDI input ports the system offers now.

    Raises whatever the backend raises when it cannot run (for example,
    without an ALSA sequencer); callers report it.
    """
    return list(mido.get_input_names())


class MidiInput:
    """One MIDI control surface, delivering its events to ``on_event``.

    ``on_event`` runs on rtmidi's thread. An exception it raises is counted
    in :attr:`errors` and never reaches rtmidi.
    """

    def __init__(self, surface: ControlSurface, on_event: Callable[[InputEvent], None]) -> None:
        self.surface = surface
        self._on_event = on_event
        self._port: Any = None
        self._beats = BeatCounter()
        self.portName: str | None = None
        self.errors = 0

    @property
    def deviceName(self) -> str:
        """What a port name must contain to match (``match.deviceName``)."""
        return self.surface["match"].get("deviceName", "")

    def open(self, names: list[str] | None = None) -> str | None:
        """Open the first port that matches, among ``names`` (default: every
        input port). Returns the port's name, or ``None`` if none matches."""
        needle = self.deviceName.casefold()
        if not needle:
            return None
        if names is None:
            names = input_names()
        name = next((n for n in names if needle in n.casefold()), None)
        if name is not None:
            self._port = mido.open_input(name, callback=self._callback)
            self.portName = name
        return name

    def close(self) -> None:
        """Close the port; no callback runs afterwards. Idempotent."""
        port, self._port = self._port, None
        if port is not None:
            port.close()

    def _callback(self, message: Any) -> None:
        try:
            event = translate(self.surface["id"], message, self._beats)
            if event is not None:
                self._on_event(event)
        except Exception:  # never into rtmidi's thread
            self.errors += 1


# -- output --------------------------------------------------------------------


def output_names() -> list[str]:
    """The MIDI output ports the system offers now (raises like
    :func:`input_names`)."""
    return list(mido.get_output_names())


def encode(address: InputAddress, kind: FeedbackKind, value: float | str) -> Any | None:
    """The mido message that shows ``value`` on ``address`` as ``kind``
    feedback (see the module docs), or ``None`` when MIDI cannot show it
    (``display`` text among others)."""
    if kind == "display" or isinstance(value, str):
        return None
    led = kind == "led"
    if address["kind"] == "midiCC":
        level = (127 if value > 0.0 else 0) if led else round(value * 127)
        return mido.Message(
            "control_change", channel=address["channel"] - 1, control=address["cc"], value=level
        )
    if address["kind"] == "midiNote":
        channel, note = address["channel"] - 1, address["note"]
        if led and value <= 0.0:
            return mido.Message("note_off", channel=channel, note=note)
        velocity = 127 if led else round(value * 127)
        return mido.Message("note_on", channel=channel, note=note, velocity=velocity)
    if address["kind"] == "midiPitchBend" and not led:
        pitch = round(value * 16383) - 8192
        return mido.Message("pitchwheel", channel=address["channel"] - 1, pitch=pitch)
    return None


class MidiOutput:
    """The feedback port of one MIDI control surface (phase-6-plan §5.9).

    Only the feedback thread sends, so a port is never written by two
    threads. :meth:`send` raises what the backend raises; the caller counts
    and reports it.
    """

    def __init__(self, surface: ControlSurface) -> None:
        self.surface = surface
        self._port: Any = None
        self.portName: str | None = None

    @property
    def deviceName(self) -> str:
        """What a port name must contain to match (``match.deviceName``)."""
        return self.surface["match"].get("deviceName", "")

    def open(self, names: list[str] | None = None) -> str | None:
        """Open the first output port that matches, among ``names`` (default:
        every output port). Returns the port's name, or ``None`` if none
        matches."""
        needle = self.deviceName.casefold()
        if not needle:
            return None
        if names is None:
            names = output_names()
        name = next((n for n in names if needle in n.casefold()), None)
        if name is not None:
            self._port = mido.open_output(name)
            self.portName = name
        return name

    def send(self, address: InputAddress, kind: FeedbackKind, value: float | str) -> None:
        """Show ``value`` on ``address`` (:func:`encode`); nothing when MIDI
        cannot show it or the port is closed."""
        message = encode(address, kind, value)
        if message is not None and self._port is not None:
            self._port.send(message)

    def close(self) -> None:
        """Close the port. Idempotent."""
        port, self._port = self._port, None
        if port is not None:
            port.close()
