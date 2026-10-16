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
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Final

from busk.commands.patch import Op
from busk.session.programmer import Programmer

LIMIT: Final = 1000
"""How many steps the timeline keeps."""


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


type Step = ShowStep | ProgrammerStep


class Timeline:
    """Undo and redo stacks. The session is the only caller (under its lock).

    Undoing is two calls: :meth:`next_undo` peeks at the step, and once the
    session has applied it successfully, :meth:`undone` moves it to the redo
    stack. A step that fails to apply therefore stays where it was.
    """

    def __init__(self, limit: int = LIMIT) -> None:
        self._undo: deque[Step] = deque(maxlen=limit)
        self._redo: list[Step] = []

    def push(self, step: Step) -> None:
        """Record a new step; this clears the redo stack."""
        self._undo.append(step)
        self._redo.clear()

    def next_undo(self) -> Step | None:
        return self._undo[-1] if self._undo else None

    def undone(self) -> None:
        self._redo.append(self._undo.pop())

    def next_redo(self) -> Step | None:
        return self._redo[-1] if self._redo else None

    def redone(self) -> None:
        self._undo.append(self._redo.pop())

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def undo_count(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)
