"""Feedback: LEDs, motor faders and labels that follow the show (phase-6-plan §5.10).

A binding with a ``feedback`` shows one value derived from its action, in
the current page's terms (decision 7): an LED (1 or 0), a motor-fader
position (0..1) or a label (OSC ``display``). :func:`feedback_values`
computes them from the engine's latest snapshot; it is pure.

======================  ====================  ==============  =======================
Action                  ``led``               ``motorFader``  ``display``
======================  ====================  ==============  =======================
``playbackFader[Abs]``  level above 0         the level       the playback's name
``playbackButton``      see below             —               the playback's name
``master``              level above 0         the level       the master's name
``tap``                 first ¼ of each beat  —               ``"<bpm> BPM"``
``blackout``            blackout on           —               —
``page {delta}``        a page that way       —               the current page's name
``pageAbs {number}``    that page current     —               that page's name
``command``             —                     —               —
======================  ====================  ==============  =======================

A button's LED follows its function: ``go``, ``back``, ``toggle``,
``release`` and ``select`` light while the playback is active; ``goto``
while it is active at its ``gotoCue``; ``flash`` while the flash is present;
``swop`` while a swop is held on it; ``none`` never. A page-relative control
on an empty slot shows 0 and an empty name. ``—`` is no value: nothing is
sent.

The **tap LED** needs the beat phase, which changes every tick and is not
in the snapshot. Each speed master's beat *anchor* is
(:class:`~busk.engine.snapshot.SpeedStatus`), and the LED is computed at the
feedback thread's own time on the engine clock.

The :class:`FeedbackWorker` runs on its own thread at :data:`FEEDBACK_HZ`:

* It sends **only changed values**. A surface that opens or reopens gets
  every value.
* **Echo hold**: a ``motorFader`` value is held back until
  :data:`ECHO_HOLD` after its control last moved (the binding resolver's
  :attr:`~busk.io.bindings.BindingResolver.lastInput`), so the motor never
  fights the operator's finger. Then the fader goes where the show is.
* It **owns the MIDI feedback ports** (:class:`~busk.io.midi.MidiOutput`),
  one per MIDI surface with feedback bindings, so a port is written by one
  thread only. It opens them when the show's surfaces change, and prints
  ``MIDI <surface> feedback: <port>`` like the inputs. Every
  :data:`~busk.io.surfaces.HOTPLUG_S` it reads the output port names and
  follows devices plugged in and unplugged, as the surface manager does for
  inputs (:func:`~busk.io.surfaces.follow_midi`, Phase 7); a reconnected
  port is a new sender, so it gets every value. Other senders (OSC
  surfaces, opened by the surface manager) come from the ``senders``
  callable.
* **Errors**: a send that raises is counted on its surface and reported
  once; the worker carries on.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, Final, Protocol

from busk.compiler.compile import CompiledShow
from busk.compiler.playbacks import CompiledPage
from busk.engine.snapshot import EngineSnapshot, PlaybackStatus, SpeedStatus
from busk.io.bindings import current_page
from busk.io.surfaces import HOTPLUG_S, MIDI_MISSING, follow_midi, open_midi
from busk.model.common import MasterId, PlaybackId, SurfaceId

if TYPE_CHECKING:  # imported where a port opens: it needs mido, the `midi` extra
    from busk.io import midi

from busk.model.surface import (
    Action,
    Binding,
    BindingFeedback,
    ControlSurface,
    FeedbackKind,
    InputAddress,
)

FEEDBACK_HZ: Final = 30.0
"""How often the feedback thread looks at the snapshot."""

ECHO_HOLD: Final = 0.5
"""Seconds without motor-fader feedback after the control moved."""

BEAT_LIT: Final = 0.25
"""The part of each beat a tap LED is lit, from the beat on."""

type FeedbackValue = float | str
"""An LED (1.0 or 0.0), a motor-fader position (0..1) or a label."""


_log = logging.getLogger("busk.surfaces")


class FeedbackSender(Protocol):
    """Where one surface's feedback goes: a MIDI output or an OSC surface."""

    def send(self, address: InputAddress, kind: FeedbackKind, value: FeedbackValue) -> None: ...


# -- values --------------------------------------------------------------------


def feedback_values(
    compiled: CompiledShow, snapshot: EngineSnapshot, now: float
) -> dict[str, FeedbackValue]:
    """Binding id → the value its feedback shows (see the module docs), for
    every binding of ``compiled`` with a ``feedback`` that shows one.

    ``snapshot`` is the engine's latest; ``now`` is the engine time, for
    the tap LEDs.
    """
    view = _View(compiled, snapshot, now)
    values: dict[str, FeedbackValue] = {}
    for binding in compiled.bindings:
        feedback = binding.get("feedback")
        if feedback is not None:
            value = view.value(binding["action"], feedback["kind"])
            if value is not None:
                values[binding["id"]] = value
    return values


def _lit(on: bool) -> float:
    return 1.0 if on else 0.0


class _View:
    """One snapshot, indexed for :func:`feedback_values`."""

    def __init__(self, compiled: CompiledShow, snapshot: EngineSnapshot, now: float) -> None:
        self.compiled = compiled
        self.snapshot = snapshot
        self.now = now
        self.page: CompiledPage | None = current_page(
            compiled, None if snapshot.page is None else snapshot.page.id
        )
        self.playbacks: dict[PlaybackId, PlaybackStatus] = {s.id: s for s in snapshot.playbacks}
        self.levels: dict[MasterId, float] = dict(snapshot.masterLevels)
        self.speed: dict[MasterId, SpeedStatus] = {s.id: s for s in snapshot.speed}

    def slot(self, slot: int) -> PlaybackStatus | None:
        """The playback on ``slot`` of the current page, if any."""
        page = self.page
        if page is None or slot >= len(page.slots):
            return None
        ident = page.slots[slot]
        return None if ident is None else self.playbacks.get(ident)

    def value(self, action: Action, kind: FeedbackKind) -> FeedbackValue | None:
        """What a binding with ``action`` shows as ``kind`` feedback."""
        if action["kind"] == "playbackFader":
            return self.fader(self.slot(action["slot"]), kind)
        if action["kind"] == "playbackFaderAbs":
            return self.fader(self.playbacks.get(action["playbackId"]), kind)
        if action["kind"] == "playbackButton":
            status = self.slot(action["slot"])
            if kind == "display":
                return "" if status is None else status.name
            if kind == "led":
                return _lit(status is not None and self.button_lit(status, action["button"]))
            return None
        if action["kind"] == "master":
            ident = action["masterId"]
            level = self.levels.get(ident, 0.0)
            if kind == "led":
                return _lit(level > 0.0)
            if kind == "motorFader":
                return level
            master = self.compiled.masters.get(ident)
            return "" if master is None else master.name
        if action["kind"] == "tap":
            speed = self.speed.get(action["masterId"])
            if kind == "led":
                return _lit(speed is not None and speed.beats(self.now) % 1.0 < BEAT_LIT)
            if kind == "display":
                return "" if speed is None else f"{round(speed.bpm, 1):g} BPM"
            return None
        if action["kind"] == "blackout":
            return _lit(self.snapshot.blackout) if kind == "led" else None
        if action["kind"] == "page":
            page, delta = self.page, action["delta"]
            if kind == "led":
                return _lit(
                    page is not None
                    and any(
                        (other.number - page.number) * delta > 0 for other in self.compiled.pages
                    )
                )
            if kind == "display":
                return "" if page is None else page.name
            return None
        if action["kind"] == "pageAbs":
            number = action["number"]
            if kind == "led":
                return _lit(self.page is not None and self.page.number == number)
            if kind == "display":
                named = (page.name for page in self.compiled.pages if page.number == number)
                return next(named, "")
            return None
        return None  # command: nothing to show

    @staticmethod
    def fader(status: PlaybackStatus | None, kind: FeedbackKind) -> FeedbackValue:
        """What a playback fader shows; ``None`` is no playback."""
        level = 0.0 if status is None else status.faderLevel
        if kind == "led":
            return _lit(level > 0.0)
        if kind == "motorFader":
            return level
        return "" if status is None else status.name

    def button_lit(self, status: PlaybackStatus, button: int) -> bool:
        """Whether button ``button`` of the playback ``status`` shows lit."""
        playback = self.compiled.playbacks.get(status.id)
        if playback is None or button >= len(playback.buttons):
            return False
        function = playback.buttons[button]
        if function == "flash":
            return status.flash
        if function == "swop":
            return status.swop
        if function == "goto":
            index = playback.gotoCue
            return (
                index is not None
                and status.state == "active"
                and status.cue == playback.cueList.cues[index].number
            )
        return function != "none" and status.state == "active"


# -- the worker ------------------------------------------------------------------


class FeedbackWorker:
    """Sends the show's feedback to its surfaces, on its own thread.

    ``compiled`` returns the latest compiled show and ``snapshot`` the
    engine's latest snapshot (``None`` before the first). ``last_input`` is
    the binding resolver's :attr:`~busk.io.bindings.BindingResolver.lastInput`,
    timed on the same clock as ``clock``, the engine's. ``senders`` returns
    the senders this worker does not own (OSC surfaces), by surface id.

    ``report`` gets the send failures and unexpected errors; ``say`` and
    ``warn`` the lines of the MIDI feedback ports opening, missing and
    reconnecting, as :func:`~busk.io.surfaces.open_midi` words them. All three
    log on ``busk.surfaces`` by default (``say`` at INFO); the CLI prints them.
    """

    def __init__(
        self,
        compiled: Callable[[], CompiledShow],
        snapshot: Callable[[], EngineSnapshot | None],
        last_input: Mapping[str, float],
        *,
        clock: Callable[[], float] = time.monotonic,
        senders: Callable[[], Mapping[SurfaceId, FeedbackSender]] = dict,
        report: Callable[[str], None] = _log.warning,
        say: Callable[[str], None] = _log.info,
        warn: Callable[[str], None] = _log.warning,
    ) -> None:
        self._latest = compiled
        self._snapshot = snapshot
        self._lastInput = last_input
        self._clock = clock
        self._senders = senders
        self._report = report
        self._say = say
        self._warn = warn
        self._compiled: CompiledShow | None = None
        self._bindings: tuple[Binding, ...] = ()  # the bindings with feedback
        self._midi: dict[SurfaceId, tuple[ControlSurface, midi.MidiOutput | None]] = {}
        """Each MIDI surface with feedback, as opened, and its output
        (``None`` when it could not open)."""
        self._sent: dict[
            SurfaceId, tuple[FeedbackSender, dict[str, tuple[BindingFeedback, FeedbackValue]]]
        ] = {}
        """Per surface: the sender, and what was last sent to it per binding."""
        self.errors: dict[SurfaceId, int] = {}
        """Failed sends per surface."""
        self._broken = False  # a failing cycle was reported
        self._hotplug_at = -math.inf  # when the output port names are read next

    def open(self) -> CompiledShow:
        """Open the MIDI outputs the latest show needs, closing the ones it
        no longer does, and return that show. :meth:`service` calls it each
        cycle; ``busk run`` calls it once before the worker's thread starts,
        so the ports' lines print with the other start-up lines."""
        compiled = self._latest()
        if compiled is not self._compiled:
            self._compiled = compiled
            self._bindings = tuple(b for b in compiled.bindings if "feedback" in b)
            self._reconcile(compiled)
        return compiled

    def service(self, now: float) -> None:
        """One cycle at engine time ``now``: send every changed value."""
        compiled = self.open()
        if now >= self._hotplug_at:
            self._hotplug_at = now + HOTPLUG_S
            self._follow_ports()
        snapshot = self._snapshot()
        if snapshot is None:
            return
        values = feedback_values(compiled, snapshot, now)
        senders: dict[SurfaceId, FeedbackSender] = {
            ident: port for ident, (_, port) in self._midi.items() if port is not None
        }
        senders.update(self._senders())
        for ident in self._sent.keys() - senders.keys():
            del self._sent[ident]
        for binding in self._bindings:
            value = values.get(binding["id"])
            surface = binding["surfaceId"]
            sender = senders.get(surface)
            if value is None or sender is None:
                continue
            record = self._sent.get(surface)
            if record is None or record[0] is not sender:  # (re)opened: send everything
                record = self._sent[surface] = (sender, {})
            sent = record[1]
            feedback = binding["feedback"]
            if sent.get(binding["id"]) == (feedback, value):
                continue
            if (
                feedback["kind"] == "motorFader"
                and now - self._lastInput.get(binding["id"], -math.inf) < ECHO_HOLD
            ):
                continue  # held back; sent once the hold is over, if still different
            sent[binding["id"]] = (feedback, value)
            try:
                sender.send(feedback["address"], feedback["kind"], value)
            except Exception as exc:
                self._failed(surface, exc)

    def _reconcile(self, compiled: CompiledShow) -> None:
        """Open a MIDI output for each MIDI surface with feedback bindings,
        and close the ones that are gone or changed (as the surface manager
        does for inputs)."""
        with_feedback = {binding["surfaceId"] for binding in self._bindings}
        wanted = {
            surface["id"]: surface
            for surface in compiled.surfaces
            if surface["kind"] == "midi" and surface["id"] in with_feedback
        }
        for ident, (surface, port) in list(self._midi.items()):
            if wanted.get(ident) != surface:
                if port is not None:
                    port.close()
                del self._midi[ident]
        for ident, surface in wanted.items():
            if ident not in self._midi:
                self._midi[ident] = (surface, self._open_port(ident, surface))

    def _open_port(self, ident: SurfaceId, surface: ControlSurface) -> midi.MidiOutput | None:
        """Open the feedback output of a MIDI surface, reporting the outcome;
        without the ``midi`` extra, say so and leave it closed."""
        label = f"MIDI {ident} feedback"
        try:
            from busk.io import midi
        except ImportError:
            self._warn(f"{label}: {MIDI_MISSING}")
            return None
        port = midi.MidiOutput(surface)
        reason = open_midi(label, port, midi.output_names, say=self._say, warn=self._warn)
        return port if reason is None else None

    def _follow_ports(self) -> None:
        """Open the feedback ports whose device appeared and close the ones
        whose port vanished (see the module docs)."""
        if not self._midi:
            return
        try:
            from busk.io import midi

            names = midi.output_names()
        except Exception:  # no MIDI backend or no mido: reported when the ports first opened
            return
        for ident, (surface, port) in list(self._midi.items()):
            make = partial(midi.MidiOutput, surface)
            followed = follow_midi(
                f"MIDI {ident} feedback", port, make, names, say=self._say, warn=self._warn
            )
            self._midi[ident] = (surface, followed)

    def _failed(self, surface: SurfaceId, exc: Exception) -> None:
        """Count a failed send, and report the first one of ``surface``."""
        count = self.errors.get(surface, 0)
        self.errors[surface] = count + 1
        if not count:
            self._report(f"feedback to {surface}: {type(exc).__name__}: {exc}")

    def run(self, stop: threading.Event) -> None:
        """Service at :data:`FEEDBACK_HZ` until ``stop`` is set, then close
        the MIDI outputs. An unexpected error is reported once and the
        cycles go on."""
        period = 1.0 / FEEDBACK_HZ
        try:
            while not stop.is_set():
                try:
                    self.service(self._clock())
                except Exception as exc:  # a bug must not end feedback
                    if not self._broken:
                        self._broken = True
                        self._report(f"feedback: {type(exc).__name__}: {exc}")
                stop.wait(period)
        finally:
            self.close()

    def close(self) -> None:
        """Close the MIDI outputs. Idempotent; call it from the worker's
        thread, or after it stopped."""
        for _, port in self._midi.values():
            if port is not None:
                port.close()
        self._midi.clear()
        self._sent.clear()
