"""The pane cursor: keyboard reach into a page (plan §4.5).

The prompt always has the keyboard. Tab on an empty prompt moves a cursor
into the visible page instead: the arrows move it over the page's items
(rows, tiles, buttons), Enter takes the item, and Esc or any printable key
gives the keyboard back to the prompt. An item either runs its line (echoed
``ui>``) or puts a line in the prompt to finish, so the cursor adds no logic
of its own: each page lists its items.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Item:
    """One thing the cursor can stop on: ``line`` runs, ``prefill`` goes to
    the prompt (one of the two)."""

    label: str
    line: str | None = None
    prefill: str | None = None


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

    def move(self, step: int) -> None:
        """``step`` items on (back when negative), stopping at the ends."""
        if self.index is not None:
            self.index = max(0, min(len(self.items) - 1, self.index + step))
