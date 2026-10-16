"""Control surfaces in ``busk run``: open while the show has them (phase-6-plan §5.13).

:class:`SurfaceManager` follows the show's ``surfaces`` through live edits:
:meth:`~SurfaceManager.reconcile` opens new or changed surfaces and closes
removed or changed ones. Each kind gets its own input:

* ``midi``: a :class:`~busk.io.midi.MidiInput`, delivering its events to the
  binding resolver;
* ``osc``: an :class:`~busk.io.osc.OscSurface`, listening on its port, whose
  feedback destination :meth:`SurfaceManager.senders` hands to the feedback
  worker;
* ``web``: a :class:`~busk.web.api.WebSurface`, serving the phone page and
  its WebSocket on its port. It restarts only when its port or host
  changes, so phones stay connected through other edits.

Opening a surface reports its lines through ``say`` (``MIDI s-nano:
<port>``, ``OSC s-touch: listening on udp 8000, feedback to the sender``,
one ``Web s-phone: http://10.0.0.5:8080/?k=…`` per address). A surface that
cannot open is reported once through ``warn``, with the reason (for a
missing MIDI device, the ports that do exist; for OSC and the web, a port in
use), and the run goes on without it. An OSC or web surface is tried again
only when an edit changes it. By default ``say`` logs at INFO and ``warn``
at WARNING on the ``busk.surfaces`` logger; the CLI passes printers for
stdout and stderr (phase-8-plan §5.6).

**MIDI hot-plug** (phase-7-plan decision 18, §5.16). Every
:data:`HOTPLUG_S` :meth:`SurfaceManager.poll` reads the MIDI input port
names once and serves every MIDI surface from that list
(:func:`follow_midi`):

* a surface that is not open and whose device now appears is opened:
  ``MIDI s-nano: <port> (connected)``;
* an open one whose port name has vanished is closed and waits for its
  device: ``MIDI s-nano: unplugged; waiting for it`` (a ``warn`` line).

rtmidi raises nothing when a device is unplugged, so the vanished name is
the only signal. ALSA gives a replugged device a new client number, so a
replug between two reads is noticed too, as a vanished and a new name. The
feedback worker does the same with the output names. A reconnected
controller's faders pick up as after any first message: the bindings' soft
takeover needs nothing more.

MIDI *feedback* ports are not opened here: the feedback thread owns them
(:class:`~busk.io.feedback.FeedbackWorker`), so a port is written by one
thread only.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Final, Protocol

from busk.compiler.compile import CompiledShow
from busk.io.events import InputEvent
from busk.io.osc import OscFeedback, OscSurface
from busk.model.common import SurfaceId
from busk.model.surface import ControlSurface
from busk.web.api import WebLink, WebSurface

if TYPE_CHECKING:  # imported where a port opens: it needs mido, the `midi` extra
    from busk.io import midi

type Opened = midi.MidiInput | OscSurface | WebSurface

_log = logging.getLogger("busk.surfaces")

type Report = Callable[[str], None]
"""Where a line goes: a printer in the CLI, a logger method by default."""

MIDI_MISSING: Final = "unavailable: install busk[midi]"
"""What a MIDI surface reports when ``mido`` is not installed (phase-8-plan §5.7)."""

HOTPLUG_S: Final = 2.0
"""Seconds between two reads of the MIDI port names (decision 18)."""


class MidiPort(Protocol):
    """A MIDI input or output of a surface: what :func:`open_midi` and
    :func:`follow_midi` need."""

    @property
    def deviceName(self) -> str: ...

    @property
    def portName(self) -> str | None: ...

    def open(self, names: list[str] | None = None) -> str | None: ...

    def close(self) -> None: ...


def open_midi(
    label: str,
    port: MidiPort,
    names: Callable[[], list[str]],
    *,
    say: Report = _log.info,
    warn: Report = _log.warning,
) -> bool:
    """Open ``port`` among the ports ``names()`` lists, and report the
    outcome after ``label``: the port's name through ``say``, or through
    ``warn`` why it did not open (for a missing device, the ports that do
    exist). ``True`` when it opened."""
    try:
        available = names()
        name = port.open(available)
    except Exception as exc:  # no ALSA sequencer, backend not loadable, …
        warn(f"{label}: unavailable: {exc}")
        return False
    if name is None:
        wanted = repr(port.deviceName) if port.deviceName else "no match.deviceName"
        warn(f"{label}: {wanted} not found; available: {', '.join(available) or 'none'}")
        return False
    say(f"{label}: {name}")
    return True


def follow_midi[P: MidiPort](
    label: str,
    port: P | None,
    make: Callable[[], P],
    names: list[str],
    *,
    say: Report = _log.info,
    warn: Report = _log.warning,
) -> P | None:
    """One hot-plug step for one MIDI port (see the module docs): ``port``
    is the open port, or ``None`` while its device is missing; ``names`` are
    the ports the system offers now. Returns the port that is open
    afterwards: ``port`` while its name is still there, a new port from
    ``make()`` once its device appears (in the same step as the old name
    vanished, for a replug between two reads), ``None`` while it is
    missing. Each change is reported after ``label`` (a connection through
    ``say``, an unplug through ``warn``); a port that appears but will not
    open is tried again on the next read, silently."""
    if port is not None:
        if port.portName in names:
            return port
        port.close()
        warn(f"{label}: unplugged; waiting for it")
    found = make()
    try:
        name = found.open(names)
    except Exception:  # busy, or gone again since the names were read
        return None
    if name is None:
        return None
    say(f"{label}: {name} (connected)")
    return found


class SurfaceManager:
    """The open control surfaces of the running show.

    ``handle`` receives every input event (the binding resolver's
    :meth:`~busk.io.bindings.BindingResolver.handle`); it runs on the
    inputs' own threads. ``web`` is what web surfaces read and submit to;
    without it they cannot open. The supervisor thread calls
    :meth:`reconcile`, :meth:`poll` and :meth:`close`; the feedback thread
    calls :meth:`senders`.
    """

    def __init__(
        self,
        handle: Callable[[InputEvent], None],
        web: WebLink | None = None,
        *,
        say: Report = _log.info,
        warn: Report = _log.warning,
    ) -> None:
        self._handle = handle
        self._web = web
        self._say = say
        self._warn = warn
        self._open: dict[SurfaceId, tuple[ControlSurface, Opened | None]] = {}
        """Each surface's definition as opened, and its input (``None`` when
        it could not open)."""
        self._osc: dict[SurfaceId, OscSurface] = {}
        """The open OSC surfaces: replaced, never changed, so the feedback
        thread can read it while the supervisor reconciles."""
        self._surfaces: tuple[ControlSurface, ...] | None = None
        self._closed = False
        self._hotplug_at = -math.inf  # when poll reads the MIDI port names next

    def reconcile(self, compiled: CompiledShow) -> None:
        """Follow ``compiled.surfaces``: close the surfaces that are gone or
        changed, then open the new and changed ones. A show whose surfaces
        are the same object as last time is skipped; after :meth:`close`
        nothing opens again."""
        surfaces = compiled.surfaces
        if self._closed or surfaces is self._surfaces:
            return
        self._surfaces = surfaces
        wanted = {s["id"]: s for s in surfaces if s["kind"] in ("midi", "osc", "web")}
        for ident, (surface, port) in list(self._open.items()):
            if ident not in wanted or not _unchanged(surface, wanted[ident]):
                if port is not None:
                    port.close()
                del self._open[ident]
        for ident, surface in wanted.items():
            if ident not in self._open:
                opening = {"midi": self._open_midi, "osc": self._open_osc, "web": self._open_web}
                self._open[ident] = (surface, opening[surface["kind"]](surface))
        self._publish()

    def poll(self, now: float) -> None:
        """Follow MIDI devices plugged in and unplugged, reading the port
        names at most every :data:`HOTPLUG_S` (``now`` is any monotonic
        time; see the module docs). Nothing happens after :meth:`close`, or
        when the MIDI backend cannot list ports (that was reported when the
        surface first tried to open)."""
        if self._closed or now < self._hotplug_at:
            return
        self._hotplug_at = now + HOTPLUG_S
        surfaces = [(i, s, p) for i, (s, p) in self._open.items() if s["kind"] == "midi"]
        if not surfaces:
            return
        try:
            from busk.io import midi

            names = midi.input_names()
        except Exception:  # no MIDI backend or no mido: reported when the surface opened
            return
        for ident, surface, port in surfaces:
            assert port is None or isinstance(port, midi.MidiInput)
            make = partial(midi.MidiInput, surface, self._handle)
            followed = follow_midi(
                f"MIDI {ident}", port, make, names, say=self._say, warn=self._warn
            )
            self._open[ident] = (surface, followed)

    def _open_midi(self, surface: ControlSurface) -> midi.MidiInput | None:
        """Open a MIDI surface's input, reporting the outcome; without the
        ``midi`` extra, say so and leave it closed."""
        label = f"MIDI {surface['id']}"
        try:
            from busk.io import midi
        except ImportError:
            self._warn(f"{label}: {MIDI_MISSING}")
            return None
        port = midi.MidiInput(surface, self._handle)
        opened = open_midi(label, port, midi.input_names, say=self._say, warn=self._warn)
        return port if opened else None

    def _open_osc(self, surface: ControlSurface) -> OscSurface | None:
        """Open an OSC surface, reporting the outcome."""
        osc = OscSurface(surface, self._handle, report=self._warn)
        reason = osc.open()
        if reason is not None:
            self._warn(f"OSC {surface['id']}: {reason}")
            return None
        self._say(f"OSC {surface['id']}: {osc.describe()}")
        return osc

    def _open_web(self, surface: ControlSurface) -> WebSurface | None:
        """Open a web surface, printing the addresses to open on a phone."""
        label = f"Web {surface['id']}"
        if self._web is None:
            self._warn(f"{label}: unavailable: no engine to serve")
            return None
        web = WebSurface(surface, self._web)
        reason = web.open()
        if reason is not None:
            self._warn(f"{label}: {reason}")
            return None
        for url in web.urls():
            self._say(f"{label}: {url}")
        return web

    def _publish(self) -> None:
        self._osc = {
            ident: port for ident, (_, port) in self._open.items() if isinstance(port, OscSurface)
        }

    def senders(self) -> dict[SurfaceId, OscFeedback]:
        """The feedback destination of each open OSC surface that has one
        (for :class:`~busk.io.feedback.FeedbackWorker`). Safe on any thread."""
        osc = self._osc
        return {ident: s.feedback for ident, s in osc.items() if s.feedback is not None}

    def close(self) -> None:
        """Close every surface; :meth:`reconcile` opens nothing afterwards."""
        self._closed = True
        for _, port in self._open.values():
            if port is not None:
                port.close()
        self._open.clear()
        self._publish()


def _unchanged(opened: ControlSurface, wanted: ControlSurface) -> bool:
    """Whether an open surface can stay open under its new definition: a web
    server only restarts when its address changes."""
    if opened["kind"] == wanted["kind"] == "web":
        old, new = opened["match"], wanted["match"]
        return (old.get("port"), old.get("host")) == (new.get("port"), new.get("host"))
    return opened == wanted
