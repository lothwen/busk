"""What every page is: a scrolling pane with an F-key, a title, and the items
the pane cursor can stop on (plan §4.5)."""

from __future__ import annotations

from textual.containers import VerticalScroll

from busk_tui.nav import Item


class Page(VerticalScroll):
    """One of the F1–F9 pages."""

    DEFAULT_CSS = "Page { height: 1fr; padding: 1 1 0 1; }"

    def __init__(self, number: int, title: str) -> None:
        super().__init__(id=f"page-{number}")
        self.can_focus = False
        self.number = number
        self.title = title

    def items(self) -> list[Item]:
        """What the pane cursor can stop on, in order."""
        return []

    def show_cursor(self, index: int | None) -> None:
        """Draw the pane cursor on item ``index`` (``None``: nowhere)."""
