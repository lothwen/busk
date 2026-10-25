"""The pane cursor: keyboard reach into a page (plan §4.5).

The prompt always has the keyboard. Tab on an empty prompt moves a cursor
into the visible page instead: the arrows move it over the page's items
(rows, tiles, buttons), Enter takes the item, and Esc or any printable key
gives the keyboard back to the prompt. An item either runs its line (echoed
``ui>``) or puts a line in the prompt to finish, so the cursor adds no logic
of its own: each page lists its items. An item may also change what the
page shows (its ``action``: F4's cue list chosen), before its line runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Item:
    """One thing the cursor can stop on: ``line`` runs, ``prefill`` goes to
    the prompt (one of the two, or neither); ``action`` is the page's own,
    called first."""

    label: str
    line: str | None = None
    prefill: str | None = None
    action: Callable[[], None] | None = None


class Markable(Protocol):
    def mark(self, index: int | None) -> None:
        """Draw the pane cursor on the part ``index`` (``None``: nowhere)."""


@dataclass(frozen=True, slots=True)
class Stop:
    """One place the cursor stops on a page: its item, and the widget (and
    the part of it) that draws the cursor."""

    item: Item
    widget: Markable
    index: int = 0


class PaneCursor:
    """Where the cursor is among a page's items; ``index`` is ``None`` while
    the prompt has the keyboard."""

    def __init__(self) -> None:
        self.items: tuple[Item, ...] = ()
        self.index: int | None = None

    @property
    def active(self) -> bool:
        return self.index is not None

    @property
    def current(self) -> Item | None:
        return None if self.index is None else self.items[self.index]

    def enter(self, items: Sequence[Item]) -> bool:
        """Move into ``items``, on the first; ``False`` if there are none."""
        self.items = tuple(items)
        self.index = 0 if self.items else None
        return self.active

    def leave(self) -> None:
        self.index = None

    def follow(self, items: Sequence[Item], label: str) -> None:
        """The page's items changed under the cursor: stay on the item with
        ``label``, else where the cursor was, within the new items."""
        self.items = tuple(items)
        found = next((i for i, item in enumerate(self.items) if item.label == label), None)
        if found is not None:
            self.index = found
        elif self.index is not None:
            self.index = min(self.index, len(self.items) - 1) if self.items else None

    def move(self, step: int, items: Sequence[Item] | None = None) -> None:
        """``step`` items on (back when negative), stopping at the ends;
        among ``items``, when the page's have changed since."""
        if items is not None:
            self.items = tuple(items)
        if self.index is not None and self.items:
            self.index = max(0, min(len(self.items) - 1, self.index + step))
