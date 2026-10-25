"""F1 Busk (spec §8.1): the performance page.

The header says which page of playbacks shows (busk's current page,
adaptation 4), which of its slots, and the selection, and has the layout
switch. The layout under it is B, the stack (adaptation 5); A and C come in
Phase 5.

The playbacks are the slots of the engine's current page, at most
``faders`` of them, or, in a show with no pages, the playbacks by number.
The selected playback (Space, ``[ ]``, ``P1`` in the prompt) is one of
them: ← → step through them, and when the page changes, the selection
moves to the playback in the same slot.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget

from busk_tui import colors
from busk_tui.formats import selection_text
from busk_tui.model import LiveState, ShowModel
from busk_tui.nav import Stop
from busk_tui.pages.base import Page, Part, View
from busk_tui.pages.busk_stack import StackLayout

LAYOUTS: Final = (("A", "console"), ("B", "stack"), ("C", "stage"))

type Slots = tuple[int | None, ...]


def visible_slots(show: ShowModel | None, live: LiveState | None, cap: int) -> Slots:
    """F1's slots: the playback number in each slot of the current page
    (``None``: empty), at most ``cap``; without pages, the playbacks by
    number."""
    if show is None:
        return ()
    if not show.pages:
        return tuple(playback.number for playback in show.playbacks)[:cap]
    current = None if live is None or live.page is None else live.page.number
    page = next((page for page in show.pages if page.number == current), show.pages[0])
    return page.slots[:cap]


def follow(selected: int, before: Slots, after: Slots) -> int:
    """The selected playback once the slots change from ``before`` to
    ``after``: itself while it shows, else the playback in its slot, else
    the first."""
    shown = [number for number in after if number is not None]
    if selected in after or not shown:
        return selected
    index = before.index(selected) if selected in before else len(after)
    in_its_slot = after[index] if index < len(after) else None
    return shown[0] if in_its_slot is None else in_its_slot


def step(selected: int, slots: Sequence[int | None], by: int) -> int:
    """The playback ``by`` slots on from ``selected`` (back when negative),
    wrapping, skipping empty slots."""
    shown = [number for number in slots if number is not None]
    if not shown:
        return selected
    if selected not in shown:
        return shown[0] if by > 0 else shown[-1]
    return shown[(shown.index(selected) + by) % len(shown)]


class BuskHeader(Widget):
    """``page 1 Main · slots 1–13 · sel 101 thru 102``, and the layouts."""

    DEFAULT_CSS = "BuskHeader { height: 1; margin-bottom: 1; }"

    def __init__(self) -> None:
        super().__init__()
        self.left = Text()
        self.shown_layout = "B"

    def show(self, view: View, slots: Slots) -> None:
        text = Text()
        live, show = view.live, view.show
        if live is not None and live.page is not None:
            text.append("page ", style=colors.DIM)
            text.append(f"{live.page.number} {live.page.name}", style=colors.FG)
            number = live.page.number
            page = (
                None if show is None else next((p for p in show.pages if p.number == number), None)
            )
            total = 0 if page is None else len(page.slots)
            text.append(" · slots ", style=colors.DIM)
            text.append(f"1–{len(slots)}" if slots else "none", style=colors.FG)
            if total > len(slots):
                text.append(f" of {total}", style=colors.DIM)
        else:
            text.append("playbacks ", style=colors.DIM)
            shown = [number for number in slots if number is not None]
            text.append(f"{shown[0]}–{shown[-1]}" if shown else "none", style=colors.FG)
        text.append(" · sel ", style=colors.DIM)
        programmer = view.programmer
        selected = (
            ""
            if programmer is None or show is None
            else selection_text(programmer.selection, show.fixtures)
        )
        text.append(selected or "none", style=colors.CYAN if selected else colors.DIM)
        if text != self.left:
            self.left = text
            self.refresh()

    def render(self) -> Text:
        right = Text("layout", style=colors.DIM)
        for letter, name in LAYOUTS:
            right.append("  ")
            click = Style(meta={"@click": f"app.layout('{letter}')"})
            if letter == self.shown_layout:
                right.append(
                    f" {letter} {name} ", style=Style(color=colors.BG, bgcolor=colors.CYAN) + click
                )
            else:
                right.append(f" {letter} ", style=Style(color=colors.CYAN) + click)
                right.append(f"{name} ", style=Style(color=colors.MID) + click)
        left = self.left.copy()
        room = self.size.width - right.cell_len - 2
        if left.cell_len > room:
            left.truncate(max(0, room), overflow="ellipsis")
        left.pad_right(self.size.width - left.cell_len - right.cell_len)
        return left + right


class BuskPage(Page):
    """F1 (see the module docs)."""

    WATCH_EFFECTS: ClassVar[bool] = True

    def __init__(self, number: int, title: str) -> None:
        super().__init__(number, title)
        self.header = BuskHeader()
        self.stack = StackLayout()

    def compose(self) -> ComposeResult:
        yield self.header
        yield self.stack

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        slots = visible_slots(view.show, view.live, view.faders)
        if changed & {"show", "live", "programmer"}:
            self.header.show(view, slots)
        self.stack.update_view(view, changed, slots)

    def stops(self) -> list[Stop]:
        return self.stack.stops()
