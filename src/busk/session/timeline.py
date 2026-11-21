"""The undo timeline: one history for show edits and programmer changes
(spec §15.4, phase-3-plan decision 6).

Show edits and programmer changes share one timeline, so one ``undo``
undoes the operator's last action, whatever it was: a selection, a value or
a record.

* A :class:`ShowStep` keeps the edit's forward and inverse patch ops. Undo
  applies the inverse to exactly the show the forward ops produced (the
  timeline is linear), redo re-applies the forward ops.
* A :class:`ProgrammerStep` keeps the programmer before and after. Only the
  selection and the values are restored: blind is a mode, not content, and
  is never undone (undoing it could put programming live on stage).

Every new step clears the redo stack. The timeline keeps at most
:data:`LIMIT` steps; the oldest are forgotten. It is not persisted.

**Undo groups** (GAP-06 of ``docs/dev/tui/engine-gaps.md``): while a
:class:`Group` is open, the programmer steps pushed join one step, labelled
as the group, which holds the programmer as it was before the first and
after the last. A show step closes the group, and so does undoing or
redoing a step. A programmer step more than :data:`GROUP_GAP` seconds after
the group's last step (or its opening) closes it too, and stands alone, so
a group nobody closes stops taking steps without a timer. A group that took
no step leaves nothing.

**Scripts** (GAP-56): while a script runs (:meth:`Timeline.open_script` to
:meth:`Timeline.close_script`), every step pushed joins one
:class:`ScriptStep`, labelled as the script, which holds the show ops of its
show steps (forward in order, inverse in reverse order) and the programmer
as it was before its first programmer step and after its last. The step
grows on top of the stack, as a group's does, so it is there from the
script's first change, and a script that stops at an error leaves the lines
that ran. ``undo`` and ``redo`` close the step so far: the steps after them
make another. A script inside a script joins the outer one. A script that
pushes nothing leaves nothing. Opening and closing a script close an undo
group, and a group opened inside a script only counts the steps that join
the script's step.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Final

from busk.commands.patch import Op
from busk.session.programmer import Programmer

LIMIT: Final = 1000
"""How many steps the timeline keeps."""

GROUP_GAP: Final = 2.0
"""Seconds after an undo group's last step that a programmer step no longer
joins it, and closes it instead."""


@dataclass(frozen=True, kw_only=True)
class ShowStep:
    """A committed show edit."""

    forward: tuple[Op, ...]
    inverse: tuple[Op, ...]
    label: str


@dataclass(frozen=True, kw_only=True)
class ProgrammerStep:
    """A programmer change (selection and values)."""

    before: Programmer
    after: Programmer
    label: str


@dataclass(frozen=True, kw_only=True)
class ScriptStep:
    """What a script changed, one step (GAP-56): its show ops, and the
    programmer before its first programmer step and after its last (``None``
    when it changed no programmer)."""

    forward: tuple[Op, ...]
    inverse: tuple[Op, ...]
    before: Programmer | None
    after: Programmer | None
    label: str


type Step = ShowStep | ProgrammerStep | ScriptStep


@dataclass(frozen=True, kw_only=True)
class Group:
    """An open undo group: its label, how many programmer steps joined it,
    and when it opened or last took one (the timeline's clock)."""

    label: str
    steps: int
    last: float


class Timeline:
    """Undo and redo stacks. The session is the only caller (under its lock).

    Undoing is two calls: :meth:`next_undo` peeks at the step, and once the
    session has applied it successfully, :meth:`undone` moves it to the redo
    stack. A step that fails to apply therefore stays where it was.

    ``clock`` gives the time in seconds that an undo group's gap is measured
    on (a monotonic clock).
    """

    def __init__(self, limit: int = LIMIT, clock: Callable[[], float] = time.monotonic) -> None:
        self._undo: deque[Step] = deque(maxlen=limit)
        self._redo: list[Step] = []
        self._clock = clock
        self._group: Group | None = None
        self._script: str | None = None  # the open script's label
        self._scripts = 0  # how deep scripts are nested
        self._joined = False  # the last step is the open script's

    def push(self, step: ShowStep | ProgrammerStep) -> None:
        """Record a new step; this clears the redo stack. A programmer step
        joins the open group, and any step the open script (see the module
        docs)."""
        group = self._group
        if group is not None:
            now = self._clock()
            if isinstance(step, ShowStep) or now - group.last > GROUP_GAP:
                self._group = None
            else:
                if self._script is None:  # in a script, the script's step takes it
                    if group.steps:  # the group's step is the last one: it grows
                        first = self._undo.pop()
                        assert isinstance(first, ProgrammerStep)
                        step = replace(first, after=step.after)
                    else:
                        step = replace(step, label=group.label)
                self._group = replace(group, steps=group.steps + 1, last=now)
        self._undo.append(step if self._script is None else self._scripted(step, self._script))
        self._redo.clear()

    def _scripted(self, step: ShowStep | ProgrammerStep, label: str) -> ScriptStep:
        """The open script's step with ``step`` joined: the last step, taken
        off the stack, or a new one labelled ``label``."""
        if self._joined:
            script = self._undo.pop()
            assert isinstance(script, ScriptStep)
        else:
            script = ScriptStep(forward=(), inverse=(), before=None, after=None, label=label)
            self._joined = True
        if isinstance(step, ShowStep):
            return replace(
                script,
                forward=script.forward + step.forward,
                inverse=step.inverse + script.inverse,
            )
        before = step.before if script.before is None else script.before
        return replace(script, before=before, after=step.after)

    def open_script(self, label: str) -> None:
        """A script starts: the steps until it ends are one, labelled
        ``label``. Inside a script, nothing changes but the depth."""
        if self._scripts == 0:
            self._group = None
            self._script = label
            self._joined = False
        self._scripts += 1

    def close_script(self) -> None:
        """The script :meth:`open_script` started ends."""
        self._scripts -= 1
        if self._scripts == 0:
            self._group = None
            self._script = None
            self._joined = False

    def open_group(self, label: str) -> Group | None:
        """Open an undo group labelled ``label``; return the group it closed, if one was open."""
        closed = self.close_group()
        self._group = Group(label=label, steps=0, last=self._clock())
        return closed

    def close_group(self) -> Group | None:
        """Close the open undo group, and return it (``None`` if none was open)."""
        group, self._group = self._group, None
        return group

    @property
    def group(self) -> Group | None:
        """The open undo group, if any."""
        return self._group

    def next_undo(self) -> Step | None:
        return self._undo[-1] if self._undo else None

    def undone(self) -> None:
        self._group = None
        self._joined = False
        self._redo.append(self._undo.pop())

    def next_redo(self) -> Step | None:
        return self._redo[-1] if self._redo else None

    def redone(self) -> None:
        self._group = None
        self._undo.append(self._redo.pop())

    def clear(self) -> None:
        self._group = None
        self._joined = False
        self._undo.clear()
        self._redo.clear()

    @property
    def undo_count(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)
