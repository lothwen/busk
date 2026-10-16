"""Bindings: input events → commands on the bus (spec §4.1, §5.15).

Bindings resolve **off the engine thread**, on the input backend's own
thread (phase-2-plan decision 10): a :class:`BindingResolver` looks up the
bindings of an event's ``(surface, input)`` and submits commands. It reads
only immutable compiled data and, for ``select`` buttons, the current page
of the engine's latest snapshot, so it holds no engine state; the one piece
of state it keeps is each button binding's edge (pressed or not).

Page-relative input is resolved **by the engine** since Phase 6 (decision
2): faders and buttons name a ``slot``, which the engine looks up on its
current page in queue order, whichever surface changed the page.

============================  ==============================================
Action                        Commands
============================  ==============================================
``playbackFader {slot}``      ``SET_FADER {slot}(value)``: the engine
                              resolves the slot on its current page
                              (Phase 6)
``playbackFaderAbs``          ``SET_FADER(value)``
``playbackButton``            ``PLAYBACK_BUTTON {slot, button, down}`` on
                              each edge: the engine applies the function
                              (Phase 6); but a ``select`` function, looked
                              up on the snapshot's page, →
                              ``SELECT_PLAYBACK`` on press, for the session
``master``                    ``SET_MASTER(value)``, every kind (fade
                              time since Phase 6)
``tap``                       ``TAP``, on press (Phase 4)
``blackout``                  ``BLACKOUT {}`` on press, which the engine
                              toggles (Phase 6); with ``momentary``,
                              ``BLACKOUT {on}`` while held
``page``, ``pageAbs``         ``PAGE {delta}``, ``PAGE {number}`` on press
                              (Phase 6)
``command``                   the embedded command, on press
anything else                 ignored (the limitation report lists it)
============================  ==============================================

Every command's origin names the surface and the **control**, the
binding's id (decision 5): the engine keeps held flashes per control.

**Soft takeover** (``faderPickup: "soft"``) is the engine's too (decision
6): the resolver sends every fader move, and the engine ignores a soft
control's moves until it meets the level, by the control in the origin.

**Buttons** are edges: a press is the value rising to ≥ 0.5, a release is
the value falling below 0.5. Each binding keeps its own edge state, so a
repeated CC 127 is still one press, and a note-on of any velocity is a
press. Each binding belongs to one surface, so to one callback thread: no
locking is needed.

**Feedback** (Phase 6). The resolver records when each binding last
received input, in :attr:`BindingResolver.lastInput`; the feedback thread
holds motor-fader feedback back for a moment after the control moved, so
the motor never fights the operator's finger (phase-6-plan §5.10).

**Errors never escape** into the backend's thread. A command the bus
rejects (or any other exception) is reported once per binding, through the
``report`` callback (by default a ``busk.surfaces`` warning; the CLI prints it
on stderr), and the binding keeps working.

**Live edits** (Phase 3). Commands go to a *sink*: the engine's bus, or the
session's :class:`~busk.session.session.InputSink`, which also takes
programmer, show-edit and session commands (the ``select`` button, a bound
``UNDO``) without blocking the input thread. With ``live``, every event first
checks the latest compiled show: when it changed, the bindings are re-read
from it (a binding that kept its id and definition keeps its edge state), so
new bindings work without a restart.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final, Protocol

from busk.commands.bus import CommandRejected
from busk.commands.types import (
    BlackoutCmd,
    Command,
    CommandOrigin,
    PageCmd,
    PlaybackButtonCmd,
    SelectPlaybackCmd,
    SetFaderCmd,
    SetMasterCmd,
    TapCmd,
)
from busk.compiler.compile import CompiledShow
from busk.compiler.playbacks import CompiledPage
from busk.io.events import AddressKey, InputEvent, address_key
from busk.model.common import PlaybackId, SurfaceId
from busk.model.show import Show
from busk.model.surface import Binding

PRESS: Final = 0.5
"""A button is pressed while its value is at least this."""


_log = logging.getLogger("busk.surfaces")


def current_page(compiled: CompiledShow, ident: str | None) -> CompiledPage | None:
    """The page of ``compiled`` with id ``ident`` (the page of an engine
    snapshot), or the lowest-numbered page, where the engine starts, when
    ``ident`` is ``None`` or names no page; ``None`` without pages.

    A snapshot can lag a live edit by a tick, so its page may be gone.
    """
    pages = compiled.pages
    return next((page for page in pages if page.id == ident), pages[0] if pages else None)


class CommandSink(Protocol):
    """Where bindings send commands: the bus, or the session's input sink."""

    def submit(self, command: Command, origin: CommandOrigin | None = None) -> object: ...


@dataclass(kw_only=True)
class _Bound:
    """A binding and its edge state."""

    binding: Binding
    pressed: bool = False

    def edge(self, value: float) -> bool | None:
        """``True`` on a press, ``False`` on a release, ``None`` otherwise."""
        if value >= PRESS and not self.pressed:
            self.pressed = True
            return True
        if value < PRESS and self.pressed:
            self.pressed = False
            return False
        return None


class BindingResolver:
    """Turns input events into commands, per the show's bindings."""

    def __init__(
        self,
        show: Show,
        compiled: CompiledShow,
        bus: CommandSink,
        report: Callable[[str], None] = _log.warning,
        *,
        live: Callable[[], CompiledShow] | None = None,
        page: Callable[[], str | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``live``, when given, returns the latest compiled show; the bindings
        then follow live edits (see the module docs). ``page`` returns the
        id of the current page in the engine's latest snapshot (``None``
        before the first one); without it, or when it names no page, a
        ``select`` button is looked up on the lowest-numbered page, where
        the engine starts. ``clock`` times :attr:`lastInput`; it must be the
        engine's clock, which the feedback thread compares it with."""
        self._compiled = compiled
        self._bus = bus
        self._report = report
        self._live = live
        self._page = page
        self._clock = clock
        self.lastInput: dict[str, float] = {}
        """Binding id → the time it last received input. Written on the
        input threads, read by the feedback thread (single dict operations,
        so no lock)."""
        self._reported: set[str] = set()  # ids of bindings whose failure was reported
        self._index: dict[tuple[SurfaceId, AddressKey], list[_Bound]] = {}
        self._reindex(show["bindings"])

    def _reindex(self, bindings: Iterable[Binding]) -> None:
        """Index ``bindings``; unchanged bindings keep their edge state."""
        previous = {
            bound.binding["id"]: bound for bounds in self._index.values() for bound in bounds
        }
        index: dict[tuple[SurfaceId, AddressKey], list[_Bound]] = {}
        for binding in bindings:
            bound = previous.get(binding["id"])
            if bound is None or bound.binding != binding:
                bound = _Bound(binding=binding)
            key = (binding["surfaceId"], address_key(binding["input"]))
            index.setdefault(key, []).append(bound)
        self._index = index

    def handle(self, event: InputEvent) -> None:
        """Submit the commands ``event`` triggers. Never raises."""
        if self._live is not None:
            compiled = self._live()
            if compiled is not self._compiled:
                self._compiled = compiled
                self._reindex(compiled.bindings)
        bounds = self._index.get((event.surfaceId, address_key(event.address)), ())
        if bounds:
            now = self._clock()
            for bound in bounds:
                self.lastInput[bound.binding["id"]] = now
        for bound in bounds:
            try:
                self._handle(bound, event)
            except CommandRejected as exc:
                self._report_once(bound, exc.reason)
            except Exception as exc:  # a bug must not kill the input thread
                self._report_once(bound, f"{type(exc).__name__}: {exc}")

    def _handle(self, bound: _Bound, event: InputEvent) -> None:
        action = bound.binding["action"]
        value = event.value
        origin = CommandOrigin(surfaceId=event.surfaceId, control=bound.binding["id"])
        if action["kind"] == "playbackFader":
            self._bus.submit(
                SetFaderCmd(type="SET_FADER", slot=action["slot"], level=value), origin
            )
        elif action["kind"] == "playbackFaderAbs":
            playback = action["playbackId"]
            self._bus.submit(
                SetFaderCmd(type="SET_FADER", playbackId=playback, level=value), origin
            )
        elif action["kind"] == "playbackButton":
            edge = bound.edge(value)
            if edge is None:
                return
            slot, button = action["slot"], action["button"]
            selected = self._selects(slot, button)
            if selected is None:
                self._bus.submit(
                    PlaybackButtonCmd(type="PLAYBACK_BUTTON", slot=slot, button=button, down=edge),
                    origin,
                )
            elif edge:
                self._bus.submit(
                    SelectPlaybackCmd(type="SELECT_PLAYBACK", playbackId=selected, mode="replace"),
                    origin,
                )
        elif action["kind"] == "master":
            master = self._compiled.masters.get(action["masterId"])
            if master is not None:
                self._bus.submit(
                    SetMasterCmd(type="SET_MASTER", masterId=master.id, level=value), origin
                )
        elif action["kind"] == "tap":
            if bound.edge(value):
                self._bus.submit(TapCmd(type="TAP", masterId=action["masterId"]), origin)
        elif action["kind"] == "blackout":
            edge = bound.edge(value)
            if action.get("momentary"):
                if edge is not None:
                    self._bus.submit(BlackoutCmd(type="BLACKOUT", on=edge), origin)
            elif edge:
                self._bus.submit(BlackoutCmd(type="BLACKOUT"), origin)
        elif action["kind"] == "page":
            if bound.edge(value):
                self._bus.submit(PageCmd(type="PAGE", delta=action["delta"]), origin)
        elif action["kind"] == "pageAbs":
            if bound.edge(value):
                self._bus.submit(PageCmd(type="PAGE", number=action["number"]), origin)
        elif action["kind"] == "command" and bound.edge(value):
            self._bus.submit(action["command"], origin)

    def _selects(self, slot: int, button: int) -> PlaybackId | None:
        """The playback a ``select`` button on ``slot`` selects, or ``None``
        when that button is not ``select`` (or the slot is empty).

        The slot is looked up on the page of the engine's latest snapshot. A
        press within one tick of a page change can see the old page; that
        race is harmless and accepted (phase-6-plan decision 4).
        """
        page = current_page(self._compiled, None if self._page is None else self._page())
        if page is None:
            return None
        playback = page.slots[slot] if slot < len(page.slots) else None
        if playback is None:
            return None
        buttons = self._compiled.playbacks[playback].buttons
        return playback if button < len(buttons) and buttons[button] == "select" else None

    def _report_once(self, bound: _Bound, reason: str) -> None:
        ident = bound.binding["id"]
        if ident not in self._reported:
            self._reported.add(ident)
            self._report(f"binding {ident}: {reason}")
