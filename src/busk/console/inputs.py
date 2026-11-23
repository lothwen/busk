"""What comes in from the control surfaces (GAP-13 of ``docs/dev/tui/engine-gaps.md``).

The binding resolver hands every input event, bound or not, to an
:class:`InputLog` with the bindings it found
(:class:`~busk.io.bindings.BindingResolver`'s ``record``). The log keeps the
newest :data:`INPUTS_KEPT` as :class:`SurfaceInput`\\ s, in the console's
words: the control as ``bind`` takes it (``cc 1 48``) and what each binding
drives as ``list bindings`` prints it (``fader 1``), so what a frontend shows
is what the operator types.

Only what reaches the bindings is logged: a MIDI message busk cannot bind
(a program change, sysex) never shows, nor does the web remote, which sends
commands, not inputs.

**Threads.** Each surface calls :meth:`InputLog.record` on its own thread.
The log is written under a lock and published as a new tuple, never changed,
so any thread reads :attr:`InputLog.inputs` whole without the lock.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from busk.console.parser import _action, _binding_names, _input
from busk.io.events import InputEvent
from busk.model.common import SurfaceId
from busk.model.show import Show
from busk.model.surface import Binding

INPUTS_KEPT: Final = 64
"""How many inputs :attr:`InputLog.inputs` keeps, the newest."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SurfaceInput:
    """One input from a control surface, as ``LiveShow.inputs`` lists it
    (GAP-13 of ``docs/dev/tui/engine-gaps.md``).

    ``seq`` counts the inputs from 1 since the surfaces opened, so a
    frontend reads only those past the last it saw. ``surfaceId`` and
    ``surface`` are the surface's id and name, ``input`` the control as
    ``bind`` takes it: ``cc 1 48``, ``note 1 60``, ``osc "/fader/1"``,
    ``clock``; a pitch bend, which ``bind`` cannot take, ``bend 1``.

    ``raw`` is the number the device sent: a CC's value and a note's
    velocity (0–127; a note off's too), a pitch bend's pitch (−8192–8191);
    ``None`` for OSC and the clock. ``value`` is what the bindings got,
    from 0 to 1: a note on is 1, a note off 0.

    ``drives`` is what each binding of the control drives, as ``list
    bindings`` prints it (``fader 1``, ``master 'Grand'``), when the input
    came in; empty for a control with no binding.
    """

    seq: int
    surfaceId: str
    surface: str
    input: str
    raw: int | None
    value: float
    drives: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Words:
    """What naming an input needs from one show document."""

    show: Show
    surfaces: Mapping[SurfaceId, str]  # surface id → name
    names: Mapping[str, Mapping[Any, Any]]  # as list bindings names what a binding drives


class InputLog:
    """The newest inputs from the control surfaces (see the module docs).

    ``show`` returns the current show document, whose names the log uses.
    """

    def __init__(self, show: Callable[[], Show]) -> None:
        self._show = show
        self._words: _Words | None = None
        self._lock = threading.Lock()
        self._kept: deque[SurfaceInput] = deque(maxlen=INPUTS_KEPT)
        self._seq = 0
        self._inputs: tuple[SurfaceInput, ...] = ()

    @property
    def inputs(self) -> tuple[SurfaceInput, ...]:
        """The newest :data:`INPUTS_KEPT` inputs, oldest first; ``()``
        before the first. Safe on any thread: replaced, never changed."""
        return self._inputs

    def record(self, event: InputEvent, bindings: Sequence[Binding]) -> None:
        """Log ``event``, with what its ``bindings`` drive."""
        words = self._words_of(self._show())
        surface = words.surfaces.get(event.surfaceId, event.surfaceId)
        control = _input(event.address)
        drives = tuple(_action(binding["action"], words.names) for binding in bindings)
        with self._lock:
            self._seq += 1
            self._kept.append(
                SurfaceInput(
                    seq=self._seq,
                    surfaceId=event.surfaceId,
                    surface=surface,
                    input=control,
                    raw=event.raw,
                    value=event.value,
                    drives=drives,
                )
            )
            self._inputs = tuple(self._kept)

    def _words_of(self, show: Show) -> _Words:
        """The names of ``show``, made once per document."""
        words = self._words
        if words is None or words.show is not show:
            surfaces = {surface["id"]: surface["name"] for surface in show["surfaces"]}
            words = _Words(show, surfaces, _binding_names(show))
            self._words = words  # one assignment: another thread sees it whole
        return words
