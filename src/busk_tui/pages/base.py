"""What every page is: a scrolling pane with an F-key, a title, and the items
the pane cursor can stop on (plan §4.5).

The app keeps one :class:`View`, the newest of everything the bridge sent
and the UI's own state, and hands it to the page on show, with the parts
that changed since (:meth:`Page.update_view`): a page redraws only those.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, Literal

from textual.containers import VerticalScroll
from textual.widget import Widget

from busk_tui.colors import ColorMode
from busk_tui.config import Layout
from busk_tui.model import (
    EffectsModel,
    LiveState,
    OutputModel,
    ProgrammerModel,
    RouteView,
    ShowModel,
    SurfaceView,
)
from busk_tui.nav import Item, Stop

type Part = Literal[
    "show", "live", "programmer", "effects", "output", "beats", "playback", "routes", "surfaces"
]

ALL_PARTS: Final[frozenset[Part]] = frozenset(
    ("show", "live", "programmer", "effects", "output", "beats", "playback", "routes", "surfaces")
)


@dataclass(slots=True)
class View:
    """What the pages show: the newest of each part the bridge sent, and the
    UI's own state."""

    show: ShowModel | None = None
    live: LiveState | None = None
    programmer: ProgrammerModel | None = None
    effects: EffectsModel | None = None
    output: OutputModel | None = None
    routes: tuple[RouteView, ...] = ()
    surfaces: tuple[SurfaceView, ...] = ()
    beats: tuple[float, ...] = ()  # each speed master's beat count, as LiveState.speed
    playback: int = 1  # the selected playback (Space, [ ], the prompt's P1)
    faders: int = 20  # at most this many slots on F1
    layout: Layout = "B"  # F1's layout: A console, B stack, C stage
    mode: ColorMode = "256"  # how the terminal shows colours
    quick: tuple[str, ...] = ()  # F2's quick lines


class Page(VerticalScroll):
    """One of the F1–F9 pages."""

    DEFAULT_CSS = "Page { height: 1fr; padding: 1 1 0 1; }"

    WATCH_EFFECTS: ClassVar[bool] = False
    """Whether the page shows the running effects (the bridge reads them
    only while such a page is visible)."""

    WATCH_OUTPUT: ClassVar[bool] = False
    """Whether the page shows the fixtures' output (read, too, only while
    such a page is visible)."""

    def __init__(self, number: int, title: str) -> None:
        super().__init__(id=f"page-{number}")
        self.can_focus = False
        self.number = number
        self.title = title
        self._stops: list[Stop] = []
        self._marked: Stop | None = None

    def update_view(self, view: View, changed: frozenset[Part]) -> None:
        """Redraw what the ``changed`` parts of ``view`` show."""

    def watches(self, view: View) -> tuple[bool, bool]:
        """Whether the page shows the output and the running effects, as
        ``view`` has it (F1's depend on its layout)."""
        return self.WATCH_OUTPUT, self.WATCH_EFFECTS

    def stops(self) -> list[Stop]:
        """Where the pane cursor stops, in order."""
        return []

    def items(self) -> list[Item]:
        """What the pane cursor can stop on, in order."""
        self._stops = self.stops()
        return [stop.item for stop in self._stops]

    def current_item(self, index: int) -> Item | None:
        """Item ``index`` as it is now (a toggle's line follows the state it
        shows); ``None`` if the page has changed under the cursor."""
        stops = self.stops()
        if index >= min(len(stops), len(self._stops)):
            return None
        if stops[index].widget is not self._stops[index].widget:
            return None
        self._stops = stops
        return stops[index].item

    def show_cursor(self, index: int | None) -> None:
        """Draw the pane cursor on item ``index`` (``None``: nowhere)."""
        if self._marked is not None:
            self._marked.widget.mark(None)
            self._marked = None
        if index is not None and index < len(self._stops):
            stop = self._stops[index]
            stop.widget.mark(stop.index)
            self._marked = stop
            if isinstance(stop.widget, Widget):
                stop.widget.scroll_visible(animate=False)
